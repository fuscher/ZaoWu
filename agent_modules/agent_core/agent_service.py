"""智能体核心服务 — 管理 LLM↔工具调用↔执行 的循环。

核心特性：
- 死循环检测：同一工具 + 相同参数连续 3 次调用 → 自动中断
- 逐轮持久化：每轮迭代结束后实时写入 SQLite，确保崩溃可恢复
- 串行执行 + 错误不终止
"""
import os
import json
import hashlib
import asyncio
import logging
import httpx
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, List, Any, Optional

from services.tool_registry import ToolRegistry
from services.tool_executor import ToolExecutor
from services.skill_registry import SkillDefinition
from agent_modules.agent_core.sandbox import SkillSandbox
from zaowu_paths import get_project_root

logger = logging.getLogger('agent_modules.agent_core.agent_service')

BASE_DIR = get_project_root()
PROVIDERS_FILE = os.path.join(BASE_DIR, 'providers.json')

# 默认系统提示词
AGENT_SYSTEM_PROMPT = """你是一个专业的 AI 编程助手，运行在 ZaoWu IDE 中。

## 身份
你是一个精通多种编程语言的资深开发者，可以操作文件系统、搜索代码、查看 Git 状态和执行终端命令。

## 工作流程
1. 理解用户的意图
2. 如果需要读取文件、搜索代码或查看 Git 状态，直接调用对应工具
3. 如果需要修改文件或执行命令，先用其他工具收集足够信息，再向用户说明将要进行的操作
4. 工具执行后，根据结果生成清晰的总结回复

## 安全规则
- 仅操作当前项目目录内的文件
- 写入文件和执行命令前确保用户知晓
- 不要执行破坏性命令（如 rm -rf 等）
- 如果工具执行失败，尝试替代方案或告知用户

## 当前项目
- 项目路径: <<PROJECT_PATH>>
- 项目结构 (顶层):
<<PROJECT_STRUCTURE>>
- Git 分支: <<GIT_BRANCH>>

## 回复风格
- 使用与用户消息相同的语言（中文或英文）
- 代码块使用正确的语言标记
- 直接给出结论和操作，避免不必要的客套话
"""


class AgentService:
    """智能体核心服务"""

    LOOP_THRESHOLD = 3  # 同一工具+参数连续调用达到此次数时自动中断
    CONFIRMATION_TIMEOUT = 60  # F11: 用户确认等待超时（秒），从 300 缩短到 60
    REQUIRES_APPROVAL_TOOLS = {'write_file', 'run_command'}

    def __init__(self, tool_registry: ToolRegistry, project_path: str = None,
                 model_id: str = '', stop_event=None, limit_path: str = None,
                 skill_registry=None):
        self.tool_registry = tool_registry
        # limit_path 独立于 project_path（展示路径）。
        # limit_path=None 时走多项目白名单；limit_path 非空时走限缩模式。
        project_bases = self._get_project_paths(limit_path)
        self.executor = ToolExecutor(tool_registry, project_bases)
        self.project_path = project_path or os.getcwd()  # 仅用于系统提示词展示
        self._model_id = model_id
        self._http_client: Optional[httpx.AsyncClient] = None
        self.stop_event = stop_event or asyncio.Event()
        # 用户确认状态：request_id -> asyncio.Event
        self._confirmation_events: Dict[str, asyncio.Event] = {}
        self._confirmation_results: Dict[str, bool] = {}
        # F12: 跟踪已发出但尚未解决的确认 request_id，避免缓存过期 id / 处理 event 尚未创建的竞态
        self._pending_confirmation_ids: set = set()
        # F04: 自动批准写入文件（由 process_message 读取 agentConfig.autoApproveWrites 设置）
        self._auto_approve_writes = False
        # Skill 注册表，可选依赖；未提供时 AgentService 行为与之前一致
        if skill_registry is None:
            from services.skill_registry import SkillRegistry
            skill_registry = SkillRegistry.get_instance()
        self.skill_registry = skill_registry

    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self._http_client

    async def process_message(self, conv_id: str, content: str) -> AsyncGenerator[str, None]:
        """处理消息，执行智能体循环，yield SSE 事件字符串"""
        try:
            conv = await self._get_conversation(conv_id)
            if not conv:
                yield self._error_event('conversation not found')
                return

            provider = self._get_provider(conv)
            if not provider:
                yield self._error_event('provider not configured')
                return

            # 从 conversation 获取 modelId，回退到 provider 的第一个模型
            self._model_id = conv.get('modelId') or next(
                iter(provider.get('models') or [{}]), {}
            ).get('id', '')

            messages = self._build_messages(conv, content)
            # F04: 读取自动批准写入配置（仅影响 write_file，run_command 仍需确认）
            agent_config = conv.get('agentConfig') or {}
            self._auto_approve_writes = agent_config.get('autoApproveWrites', False)
            sandbox = self._build_sandbox(conv)
            tool_specs = sandbox.build_openai_tools_spec()

            assistant_msg_id = f'agent-{_now_ts()}'

            # 死循环检测：记录 (tool_name, args_hash) 调用历史
            tool_call_history: List[tuple] = []
            max_iterations = agent_config.get('maxIterations', 10)

            # full_text 在循环外初始化，跨迭代累加，保留中间推理过程
            full_text = ''

            for iteration in range(max_iterations):
                # 检查停止事件
                if self.stop_event.is_set():
                    yield self._text_event('[系统] 生成已被用户终止')
                    yield self._done_event(assistant_msg_id, full_text or '(stopped)')
                    return

                collected_tool_calls = []
                collected_text = ''

                # Step 1: 流式调用 LLM
                async for event in self._stream_llm(
                    provider, messages, tool_specs,
                    temperature=conv.get('temperature', 0.7),
                    max_tokens=conv.get('maxTokens', 4096),
                    top_p=conv.get('topP', 1.0),
                    stop_event=self.stop_event,
                ):
                    if event.get('type') == 'delta':
                        collected_text += event.get('delta', '')
                        yield self._delta_event(assistant_msg_id, event['delta'])
                    elif event.get('type') == 'tool_call_part':
                        collected_tool_calls = self._merge_tool_call(
                            collected_tool_calls, event['tool_call']
                        )

                # 累加本轮文本到 full_text，保留中间推理过程
                if collected_text:
                    full_text += collected_text + '\n'

                # Step 2: 如果有工具调用
                if collected_tool_calls:
                    # 2a: F05 连续死循环检测 — 检测尾部连续重复（跨迭代延续），而非全局累计计数
                    # 从 tool_call_history 尾部延续 streak，使跨迭代的单次重复调用也能被检测到，
                    # 同时避免 A-B-A-B-A 交替模式被误判（streak 在每次切换时重置）。
                    keys = [
                        (tc['name'], self._hash_args(tc['arguments']))
                        for tc in collected_tool_calls
                    ]
                    streak = 0
                    last_key = None
                    if tool_call_history:
                        last_key = tool_call_history[-1]
                        for k in reversed(tool_call_history):
                            if k == last_key:
                                streak += 1
                            else:
                                break
                    for key in keys:
                        if key == last_key:
                            streak += 1
                        else:
                            last_key = key
                            streak = 1
                        if streak >= self.LOOP_THRESHOLD:
                            yield self._text_event(
                                f'[系统] 检测到连续重复调用 `{key[0]}` 已达 '
                                f'{self.LOOP_THRESHOLD} 次，已自动中断循环'
                            )
                            yield self._done_event(assistant_msg_id,
                                                   full_text or '(loop detected, stopped)')
                            return
                    # 通过检测后插入到调用历史（用于后续轮的 streak 延续）
                    tool_call_history.extend(keys)

                    # 2b: 发送 tool_call_start 事件
                    for tc in collected_tool_calls:
                        yield self._tool_call_start_event(assistant_msg_id, tc)

                    # 2c: F04+F12+F13 串行执行工具（危险工具需用户确认），收集结果后批量注入
                    tool_results = []
                    for tc in collected_tool_calls:
                        if tc['name'] in self.REQUIRES_APPROVAL_TOOLS:
                            # F04: run_command 永远需要确认，write_file 可被 autoApproveWrites 跳过
                            if not (tc['name'] == 'write_file' and self._auto_approve_writes):
                                # F12: 先注册 pending id，处理用户批准早于 event 创建的竞态
                                self._pending_confirmation_ids.add(tc['requestId'])
                                yield self._requires_confirmation_event(assistant_msg_id, tc)
                                approved = await self._wait_for_confirmation(tc['requestId'])
                                if not approved:
                                    result = {
                                        'success': False,
                                        'error': '用户已拒绝执行该操作',
                                        'content': '',
                                    }
                                    yield self._tool_call_end_event(
                                        assistant_msg_id, tc['requestId'], result
                                    )
                                    tool_results.append(result)
                                    continue

                        result = await sandbox.execute(tc['name'], tc['arguments'])
                        yield self._tool_call_end_event(assistant_msg_id, tc['requestId'], result)
                        tool_results.append(result)

                    # F13: 批量注入消息历史（合并为一条 assistant 消息 + N 条 tool 结果，符合 OpenAI 格式）
                    await self._inject_tool_results_batch(
                        messages, conv_id, collected_tool_calls, tool_results
                    )
                else:
                    # 无工具调用，退出循环
                    break

            # Step 3: 发送完成事件，持久化最终消息
            yield self._done_event(assistant_msg_id, full_text or '(tool execution completed)')
            await self._append_message(conv_id, {
                'id': assistant_msg_id,
                'role': 'assistant',
                'content': full_text or '(tool execution completed)',
                'timestamp': _now_ts(),
                'model': self._model_id,
            })
        except Exception as e:
            # F08: 捕获未处理异常，保证 SSE 流始终以 done 事件结束，前端 isStreaming 可正常重置
            logger.exception('unhandled error in agent process_message')
            yield self._text_event(f'[系统] 智能体运行异常: {str(e)}')
            yield self._done_event(f'agent-error-{_now_ts()}', f'(error: {str(e)})')
        finally:
            pass  # 统一由路由层的 finally await agent.close() 处理

    # ── 工具结果注入与持久化 ─────────────────────────────────

    async def _inject_tool_results_batch(
        self, messages: list, conv_id: str,
        collected_tool_calls: list, tool_results: list
    ) -> None:
        """F13: 将一轮中的所有工具调用合并为一条标准 assistant 消息 + N 条 tool 结果

        符合 OpenAI 消息格式：一条含 tool_calls 的 assistant 消息，后跟每条 tool 结果。
        修复原 _inject_tool_result 为每个工具调用单独生成 assistant 消息的非标准结构。
        """
        if not collected_tool_calls:
            return

        # 合并为一条 assistant 消息
        tool_calls_block = []
        for tc in collected_tool_calls:
            tool_calls_block.append({
                'id': tc['requestId'],
                'type': 'function',
                'function': {
                    'name': tc['name'],
                    'arguments': json.dumps(tc['arguments'], ensure_ascii=False),
                }
            })

        assistant_msg = {
            'role': 'assistant',
            'content': None,
            'tool_calls': tool_calls_block,
        }
        messages.append(assistant_msg)
        await self._append_message(conv_id, assistant_msg)

        # 依次追加 tool 结果
        for tc, result in zip(collected_tool_calls, tool_results):
            tool_msg = {
                'role': 'tool',
                'tool_call_id': tc['requestId'],
                'name': tc['name'],
                'content': json.dumps(result, ensure_ascii=False),
            }
            messages.append(tool_msg)
            await self._append_message(conv_id, tool_msg)

    # ── 用户确认 ──────────────────────────────────────────────

    def submit_confirmation(self, request_id: str, approved: bool) -> bool:
        """F12: 由路由层调用，提交用户对指定 tool requestId 的确认结果

        只有真正待确认（在 _pending_confirmation_ids 中）或正在等待 event 的 request_id 才接受，
        避免缓存过期 id 或处理伪造/重复确认。
        """
        if (request_id not in self._pending_confirmation_ids
                and request_id not in self._confirmation_events):
            return False

        self._pending_confirmation_ids.discard(request_id)
        self._confirmation_results[request_id] = approved

        event = self._confirmation_events.get(request_id)
        if event:
            event.set()
        return True

    async def _wait_for_confirmation(self, request_id: str) -> bool:
        """F12: 阻塞等待用户确认，超时或停止时返回 False

        处理用户批准早于 event 创建的竞态：先检查预缓存结果。
        """
        # 先检查是否有预缓存的确认结果（用户点击比 event 创建更快）
        if request_id in self._confirmation_results:
            self._pending_confirmation_ids.discard(request_id)
            return self._confirmation_results.pop(request_id)

        event = asyncio.Event()
        self._confirmation_events[request_id] = event
        try:
            done, pending = await asyncio.wait(
                [asyncio.create_task(event.wait()),
                 asyncio.create_task(self.stop_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=self.CONFIRMATION_TIMEOUT,
            )
            for task in pending:
                task.cancel()
            if not done:
                # 超时
                return False
            # 检查是确认事件还是停止事件先触发
            if event.is_set():
                return self._confirmation_results.get(request_id, False)
            return False
        finally:
            self._pending_confirmation_ids.discard(request_id)
            self._confirmation_events.pop(request_id, None)
            self._confirmation_results.pop(request_id, None)

    # ── 死循环检测 ────────────────────────────────────────────

    @staticmethod
    def _hash_args(args: dict) -> str:
        """对参数字典计算 hash，用于循环检测"""
        raw = json.dumps(args, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    # ── 消息构建 ──────────────────────────────────────────────

    async def _get_conversation(self, conv_id: str) -> Optional[dict]:
        from server_quart import get_conversation_store
        try:
            return await get_conversation_store().get(conv_id)
        except Exception:
            logger.exception('failed to read conversation %s', conv_id)
            return None

    def _get_provider(self, conv: dict) -> Optional[dict]:
        provider_id = conv.get('providerId', '')
        try:
            with open(PROVIDERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return next((p for p in data.get('providers', []) if p['id'] == provider_id), None)
        except Exception:
            return None

    def _build_messages(self, conv: dict, user_content: str) -> List[Dict[str, Any]]:
        """构建消息列表：系统提示词 + 历史（含 tool_calls/tool 角色）"""
        messages = []

        # 系统提示词
        system_prompt = self._build_system_prompt(conv)
        messages.append({'role': 'system', 'content': system_prompt})

        # 对话历史（保留 tool_calls 和 tool 角色）
        for msg in conv.get('messages', []):
            if msg.get('role') == 'system':
                continue
            entry = {'role': msg['role'], 'content': msg.get('content')}
            if msg.get('tool_calls'):
                entry['tool_calls'] = msg['tool_calls']
            if msg.get('tool_call_id'):
                entry['tool_call_id'] = msg['tool_call_id']
            if msg.get('name'):
                entry['name'] = msg['name']
            messages.append(entry)

        # 用户消息已在路由层写入 conversations.json，此处不再追加
        # 避免用户消息在 LLM 上下文中重复出现

        return messages

    def _resolve_skill_config(self, conv: dict) -> Dict[str, Any]:
        """解析当前选中 skill 的最终配置。

        配置优先级（从高到低）：
        1. conv.agentConfig.skillConfig[skill.name]
        2. SkillDefinition.default_config（其中 manifest.config 已在加载阶段合并）
        """
        agent_config = conv.get('agentConfig') or {}
        skill_name = agent_config.get('selectedSkill')
        if not skill_name:
            return {}

        skill = self.skill_registry.get(skill_name)
        if not skill:
            return {}

        merged = dict(skill.default_config)
        user_skill_config = (agent_config.get('skillConfig') or {}).get(skill_name) or {}
        merged.update(user_skill_config)
        return merged

    def _get_selected_skill(self, conv: dict) -> Optional[SkillDefinition]:
        """Return the selected skill if it exists and is enabled.

        Logs a warning and returns ``None`` when no skill is selected, the skill
        does not exist, or it is disabled.  This centralises the lookup logic used
        by both the sandbox and system prompt builders.
        """
        agent_config = conv.get('agentConfig') or {}
        skill_name = agent_config.get('selectedSkill')
        if not skill_name:
            return None

        skill = self.skill_registry.get(skill_name)
        if skill is None:
            logger.warning('selected skill %r not found', skill_name)
            return None
        if not self.skill_registry.is_enabled(skill_name):
            logger.warning('selected skill %r is disabled', skill_name)
            return None
        return skill

    def _build_sandbox(self, conv: dict) -> SkillSandbox:
        """根据当前选中的 Skill 构建工具调用沙箱。

        若 Skill 声明了 ``allowed_tools`` 白名单，则 LLM 只能看到并使用这些工具；
        否则放行全部工具，保持原有行为。
        """
        skill = self._get_selected_skill(conv)
        allowed_tools: set[str] = set()

        if skill is None:
            logger.debug('no selected skill; sandbox unrestricted')
        elif skill.allowed_tools:
            allowed_tools = set(skill.allowed_tools)
            logger.debug('skill %r restricts tools to %s', skill.name, sorted(allowed_tools))

        return SkillSandbox(self.tool_registry, self.executor, allowed_tools)

    def _build_system_prompt(self, conv: dict) -> str:
        """构建系统提示词，注入运行时上下文与选中技能。

        Skill 提示词追加在默认系统提示词之后，以 "## 当前技能" 分隔。
        若 selectedSkill 不存在或已禁用，则追加警告提示。
        """
        agent_config = conv.get('agentConfig') or {}
        system_prompt = agent_config.get('systemPrompt') or AGENT_SYSTEM_PROMPT

        project_structure = self._get_project_structure()
        git_branch = self._get_git_branch()

        system_prompt = system_prompt.replace('<<PROJECT_PATH>>', self.project_path)
        system_prompt = system_prompt.replace('<<PROJECT_STRUCTURE>>', project_structure)
        system_prompt = system_prompt.replace('<<GIT_BRANCH>>', git_branch)

        # 注入技能提示词（追加模式）
        selected_skill_name = agent_config.get('selectedSkill')
        if selected_skill_name:
            skill = self._get_selected_skill(conv)
            if skill is None:
                warning = (
                    f"⚠️ 选中的技能 '{selected_skill_name}' 不存在或已被禁用，"
                    f"将以默认模式继续。"
                )
                system_prompt += f"\n\n{warning}"
            elif skill.system_prompt:
                system_prompt += f"\n\n## 当前技能\n\n{skill.system_prompt}"

            # 注入 skill 最终配置（default_config + manifest.config + skillConfig 合并）
            skill_config = self._resolve_skill_config(conv)
            if skill_config:
                system_prompt += (
                    f"\n\n## 技能配置\n\n"
                    f"```json\n{json.dumps(skill_config, ensure_ascii=False, indent=2)}\n```"
                )

        return system_prompt

    # ── 逐轮持久化 ────────────────────────────────────────────

    async def _append_message(self, conv_id: str, msg: dict) -> None:
        """逐轮持久化：单行 INSERT 到 SQLite，不再全量读写 JSON。"""
        try:
            from services.data_lock import conversation_lock as _chat_lock
            from server_quart import get_conversation_store
            with _chat_lock:
                if 'timestamp' not in msg:
                    msg['timestamp'] = _now_ts()
                if 'updatedAt' not in msg:
                    msg['updatedAt'] = datetime.now(timezone.utc).isoformat()
                await get_conversation_store().append_message(conv_id, msg)
        except Exception:
            logger.exception('failed to append message to conversation %s', conv_id)

    # ── 上下文注入 ────────────────────────────────────────────

    @staticmethod
    def _get_project_paths(limit_path: str = None) -> list:
        """获取所有活跃项目路径（多项目白名单）

        从 projects.json 读取所有注册项目，过滤已归档项目及无效路径。
        如果指定了 limit_path（来自 agentConfig.projectPath），则仅返回该项。
        """
        if limit_path and os.path.isdir(limit_path):
            return [os.path.realpath(limit_path)]

        paths = []
        try:
            from routes.explorer import read_projects
            projects = read_projects()
            for p in projects:
                p_path = p.get('path', '')
                if not p_path or not os.path.isdir(p_path):
                    continue
                # 检查是否已归档（读取 .zaowu 文件中的 archived 字段）
                zaowu_path = os.path.join(p_path, '.zaowu')
                if os.path.exists(zaowu_path):
                    try:
                        with open(zaowu_path, 'r', encoding='utf-8') as f:
                            meta = json.load(f)
                            if meta.get('archived', False):
                                continue
                    except (json.JSONDecodeError, IOError):
                        pass
                paths.append(os.path.realpath(p_path))
        except Exception:
            pass

        if not paths:
            # F19: 无项目时回退到用户主目录 ~/.ZaoWu 安全沙箱，而非 os.getcwd()（服务器启动目录，
            # 可能暴露 providers.json API Key 与全部源码）。目录不存在时自动创建。
            home_zaowu = os.path.join(os.path.expanduser('~'), '.ZaoWu')
            os.makedirs(home_zaowu, exist_ok=True)
            paths.append(home_zaowu)
        return paths

    def _get_project_structure(self) -> str:
        """获取项目顶层结构（最多 30 项）"""
        try:
            entries = sorted(os.scandir(self.project_path),
                           key=lambda e: (not e.is_dir(), e.name.lower()))
            lines = []
            count = 0
            for entry in entries:
                if entry.name.startswith('.') and entry.name != '.gitignore':
                    continue
                prefix = '[dir]' if entry.is_dir() else '[file]'
                lines.append(f'  {prefix} {entry.name}')
                count += 1
                if count >= 30:
                    lines.append(f'  ... (and more)')
                    break
            return '\n'.join(lines) if lines else '(empty)'
        except Exception:
            return '(unavailable)'

    def _get_git_branch(self) -> str:
        """获取当前 Git 分支"""
        try:
            import subprocess
            result = subprocess.run(
                ['git', 'branch', '--show-current'],
                cwd=self.project_path,
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() or '(not a git repo)'
        except Exception:
            return '(unavailable)'

    # ── LLM 流式调用 ──────────────────────────────────────────

    async def _stream_llm(
        self,
        provider: dict,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float = 1.0,
        stop_event=None,
    ) -> AsyncGenerator[dict, None]:
        """流式调用 LLM，yield 解析后的事件字典"""
        api_base = provider.get('apiBase', '').rstrip('/')
        api_key = provider.get('apiKey', '')
        model_id = self._model_id or ''

        payload = {
            'model': model_id,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'top_p': top_p,
            'stream': True,
        }
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }

        accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}

        try:
            async with self.http_client.stream(
                'POST',
                f'{api_base}/chat/completions',
                json=payload,
                headers=headers,
            ) as response:
                # 明确指定 UTF-8，防止上游未声明 charset 时产生中文乱码。
                response.encoding = 'utf-8'

                if response.status_code != 200:
                    body = await response.aread()
                    yield {
                        'type': 'delta',
                        'delta': f'API 请求失败 (HTTP {response.status_code}): {body.decode()[:200]}',
                    }
                    return

                async for line in response.aiter_lines():
                    # 检查停止事件
                    if stop_event and stop_event.is_set():
                        break

                    if not line.startswith('data: '):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data_str)
                        choice = chunk.get('choices', [{}])[0]
                        delta = choice.get('delta', {})

                        # 文本增量
                        if 'content' in delta and delta['content']:
                            yield {'type': 'delta', 'delta': delta['content']}

                        # 工具调用增量（累加）
                        if 'tool_calls' in delta:
                            for tc in delta['tool_calls']:
                                idx = tc.get('index', 0)
                                if idx not in accumulated_tool_calls:
                                    accumulated_tool_calls[idx] = {
                                        'id': tc.get('id', '') or f'tool_{idx}',
                                        'type': 'function',
                                        'function': {'name': '', 'arguments': ''},
                                    }
                                acc = accumulated_tool_calls[idx]
                                if 'id' in tc and tc['id']:
                                    acc['id'] = tc['id']
                                func = tc.get('function', {})
                                if 'name' in func:
                                    acc['function']['name'] += func['name']
                                if 'arguments' in func:
                                    acc['function']['arguments'] += func['arguments']

                    except json.JSONDecodeError:
                        continue

            # 流结束，产出完整的工具调用
            if accumulated_tool_calls:
                for tc in sorted(accumulated_tool_calls.values(), key=lambda x: x.get('id', '')):
                    func = tc['function']
                    try:
                        parsed_args = json.loads(func['arguments']) if func['arguments'] else {}
                    except json.JSONDecodeError:
                        parsed_args = {}

                    yield {
                        'type': 'tool_call_part',
                        'tool_call': {
                            'requestId': tc['id'],
                            'name': func['name'],
                            'arguments': parsed_args,
                        }
                    }

        except httpx.TimeoutException:
            yield {'type': 'delta', 'delta': '\n\n[请求超时]'}
        except httpx.ConnectError:
            yield {'type': 'delta', 'delta': '\n\n[无法连接到 API 服务器]'}

    @staticmethod
    def _merge_tool_call(existing: list, new: dict) -> list:
        """合并工具调用（去重，更新）

        防御性代码：_stream_llm 已在流结束后产出完整的工具调用（按 index 分离），
        正常路径下此方法仅做 append。保留合并逻辑以应对 Provider 异常行为。
        """
        for ex in existing:
            if ex['requestId'] == new['requestId']:
                ex['name'] = new['name']
                ex['arguments'] = new['arguments']
                return existing
        existing.append(new)
        return existing

    # ── SSE 事件格式化 ──────────────────────────────────────

    @staticmethod
    def _delta_event(msg_id: str, delta: str) -> str:
        return f'data: {json.dumps({"id": msg_id, "type": "delta", "delta": delta, "done": False}, ensure_ascii=False)}\n\n'

    @staticmethod
    def _text_event(text: str) -> str:
        return f'data: {json.dumps({"id": "system", "type": "delta", "delta": text, "done": False}, ensure_ascii=False)}\n\n'

    @staticmethod
    def _tool_call_start_event(msg_id: str, tc: dict) -> str:
        return f'data: {json.dumps({"id": msg_id, "type": "tool_call_start", "toolCall": tc}, ensure_ascii=False)}\n\n'

    @staticmethod
    def _requires_confirmation_event(msg_id: str, tc: dict) -> str:
        return f'data: {json.dumps({"id": msg_id, "type": "requires_confirmation", "toolCall": tc}, ensure_ascii=False)}\n\n'

    @staticmethod
    def _tool_call_end_event(msg_id: str, request_id: str, result: dict) -> str:
        return f'data: {json.dumps({"id": msg_id, "type": "tool_call_end", "toolResult": {**result, "requestId": request_id}}, ensure_ascii=False)}\n\n'

    @staticmethod
    def _done_event(msg_id: str, content: str) -> str:
        return f'data: {json.dumps({"id": msg_id, "type": "done", "content": content, "done": True}, ensure_ascii=False)}\n\n'

    @staticmethod
    def _error_event(error: str) -> str:
        return f'data: {json.dumps({"id": "error", "type": "done", "content": error, "done": True}, ensure_ascii=False)}\n\n'

    async def close(self):
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)
