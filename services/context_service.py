"""上下文源化 + token 预算 + 压缩（阶段二）。

职责：
- 5.1 ``ContextService.build``：把每轮全量重拼的系统提示词改为有序源。
  静态段为常量；动态段（项目结构/git 分支/项目路径）按 TTL 缓存；
  技能段（提示词 + 配置）按 ``SkillRegistry.version`` 失效（N2-M1，不引入事件总线）。
  占位符替换作为最终后处理，对默认/自定义 prompt 统一生效（N2-I3）。
- 5.2 ``estimate_tokens`` + ``compact_if_needed``：长对话显式摘要化，
  摘要落 ``conversations.compaction_summary``（M2 修复：不被 _build_messages skip）。

生命周期（N2-I1）：每会话实例，由 AgentService 持有；不做全局单例——
否则 project_structure/skill_config 缓存会串会话。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger('services.context_service')

# 近期窗口保护：刚发生的上下文不被压缩吃掉（字符数）
PRUNE_MINIMUM = 20_000


def estimate_tokens(text: str) -> int:
    """混合 token 估算（M3 修复）。

    ``len(text)//4`` 是英文经验值，对中文低估 3~4 倍（中文约 1 字符/token），
    会导致预算长期判定"未超限"而实际已超限，压缩永远来不及触发。
    改用：非 ASCII（中文/CJK 等）按 1 token/字符，ASCII 按 4 字符/token。
    偏高估倾向早压缩，配合 4.1 的 context_overflow 错误双触发兜底。
    """
    if not text:
        return 0
    cjk = sum(1 for c in text if ord(c) > 127)
    ascii_chars = len(text) - cjk
    return cjk + ascii_chars // 4


def estimate_message_tokens(msg: dict) -> int:
    """估算单条消息 token：content + tool_calls 的 function name/arguments。

    工具轮 assistant 消息 content 为 None，tool_calls 的 arguments 是主要 token 消耗，
    若不统计会让工具密集长对话被系统性低估，压缩触发过晚。
    （OpenAI 存储格式：arguments 落库时已是 JSON 字符串。）
    """
    parts = [msg.get('content') or '']
    for tc in msg.get('tool_calls') or []:
        fn = tc.get('function') or {}
        args = fn.get('arguments')
        if not isinstance(args, str):
            # 防御：内存 dict 形态的调用方（未序列化）
            args = json.dumps(args or {}, ensure_ascii=False)
        parts.append(fn.get('name', ''))
        parts.append(args)
    return estimate_tokens('\n'.join(parts))


class ContextService:
    """每会话上下文服务（N2-I1：每会话实例，挂 AgentService）。"""

    PROJECT_PATH_TTL = 300.0   # 多项目白名单 5min
    STRUCTURE_TTL = 60.0       # 项目结构 60s
    GIT_BRANCH_TTL = 60.0      # git 分支 60s

    def __init__(self, agent_service, default_prompt: str = '') -> None:
        self._agent = agent_service
        # 默认系统提示词（由 AgentService 传入，避免 services→agent_modules 循环导入）
        self._default_prompt = default_prompt
        # TTL 缓存：key -> (value, rendered_at)
        self._ttl_cache: Dict[str, Tuple[str, float]] = {}
        # 技能版本缓存：key -> (text, skill_version)
        self._skill_cache: Dict[str, Tuple[str, int]] = {}

    # ── 5.1 系统提示词构建 ─────────────────────────────────────

    async def build(self, conv: dict) -> str:
        """构建系统提示词（5.1）。

        - 默认 prompt：``default_prompt`` 常量 + 技能源 + 占位符替换。
        - 自定义 prompt（I4）：用户 prompt 整段作为基座，仅叠加技能源与占位符替换，
          不套用静态源拆分（自定义段落结构不可预知）。
        """
        agent_config = conv.get('agentConfig') or {}
        custom = agent_config.get('systemPrompt')
        body = custom if custom else self._default_prompt

        # 技能源（version 缓存）——默认/自定义都叠加
        body += await self._render_skills()
        body += await self._render_skill_config(conv)

        # 占位符替换（N2-I3，最终后处理；TTL 缓存值）
        body = await self._replace_placeholders(body)
        return body

    async def _render_skills(self) -> str:
        """已启用技能的 system_prompt 拼接（按 name 字典序）。按 skill_registry.version 失效。"""
        version = self._agent.skill_registry.version
        cached = self._skill_cache.get('skills')
        if cached and cached[1] == version:
            return cached[0]
        parts: List[str] = []
        for skill in self._agent._get_enabled_skills():
            if skill.system_prompt:
                parts.append(f"\n\n## 当前技能：{skill.name}\n\n{skill.system_prompt}")
        text = ''.join(parts)
        self._skill_cache['skills'] = (text, version)
        return text

    async def _render_skill_config(self, conv: dict) -> str:
        """合并后的技能配置 JSON。按 skill_registry.version 失效。"""
        version = self._agent.skill_registry.version
        cached = self._skill_cache.get('skill_config')
        if cached and cached[1] == version:
            return cached[0]
        skill_config = self._agent._resolve_merged_skill_config(conv)
        text = ''
        if skill_config:
            text = (
                f"\n\n## 技能配置\n\n"
                f"```json\n{json.dumps(skill_config, ensure_ascii=False, indent=2)}\n```"
            )
        self._skill_cache['skill_config'] = (text, version)
        return text

    async def _replace_placeholders(self, text: str) -> str:
        """占位符替换（N2-I3）：对默认/自定义 prompt 都生效，用 TTL 缓存值。"""
        if '<<PROJECT_PATH>>' in text:
            text = text.replace('<<PROJECT_PATH>>', await self._project_paths_value())
        if '<<PROJECT_STRUCTURE>>' in text:
            text = text.replace('<<PROJECT_STRUCTURE>>', await self._project_structure_value())
        if '<<GIT_BRANCH>>' in text:
            text = text.replace('<<GIT_BRANCH>>', await self._git_branch_value())
        return text

    async def _ttl_get(self, key: str, ttl: float, producer) -> str:
        cached = self._ttl_cache.get(key)
        if cached and (time.time() - cached[1]) < ttl:
            return cached[0]
        value = await producer()
        self._ttl_cache[key] = (value, time.time())
        return value

    async def _project_paths_value(self) -> str:
        async def produce() -> str:
            return '\n'.join(f'- {p}' for p in self._agent.executor.project_bases)
        return await self._ttl_get('project_paths', self.PROJECT_PATH_TTL, produce)

    async def _project_structure_value(self) -> str:
        # _get_project_structure 是同步 scandir，放线程池避免阻塞
        async def produce() -> str:
            return await asyncio.to_thread(self._agent._get_project_structure)
        return await self._ttl_get('project_structure', self.STRUCTURE_TTL, produce)

    async def _git_branch_value(self) -> str:
        async def produce() -> str:
            return await asyncio.to_thread(self._agent._get_git_branch)
        return await self._ttl_get('git_branch', self.GIT_BRANCH_TTL, produce)

    # ── 5.2 token 预算 + 压缩 ──────────────────────────────────

    async def compact_if_needed(
        self, conv: dict, system_prompt: str, max_tokens: int, provider: dict,
    ) -> Tuple[Optional[List[dict]], Optional[str]]:
        """主动压缩（预算触发）。

        在 conv['messages']（携带 seq）上工作：估算 system+历史 token，超 0.8*max_tokens
        时把早期消息摘要化。摘要落 ``conversations.compaction_summary``（M2 修复），
        由 ``_build_messages`` 主动注入；messages 表的 [compaction] 标记仅作审计。

        返回 ``(new_messages, summary)``：需要压缩时 new_messages 为新 LLM 消息列表、
        summary 为摘要文本；无需压缩时两者均为 None（调用方保持原 messages）。
        """
        conv_id = conv['id']
        existing_summary = conv.get('compactionSummary')
        compacted_until = conv.get('compactedUntilSeq', -1)

        # 历史消息（跳过 system 与已被压缩的早期消息）
        history = [
            m for m in conv.get('messages', [])
            if m.get('role') != 'system'
            and m.get('seq', -1) > compacted_until
        ]
        if not history:
            return None, None

        total = estimate_tokens(system_prompt) + sum(
            estimate_message_tokens(m) for m in history
        )
        if total <= int(max_tokens * 0.8):
            return None, None  # 未超预算

        recent, old = self._split_window(history, PRUNE_MINIMUM)
        if not old:
            # 近期窗口已占满全部历史，无可压缩空间
            return None, None

        summary = await self._summarize(existing_summary, old, provider)
        compacted_until_seq = max((m.get('seq', -1) for m in old), default=-1)

        # 持久化摘要（M2：落 conversations 表，非 messages 表 system 行）
        try:
            from server_quart import get_conversation_store
            from datetime import datetime, timezone
            store = get_conversation_store()
            await store.update(conv_id, {
                'compactionSummary': summary,
                'compactedUntilSeq': compacted_until_seq,
                'updatedAt': datetime.now(timezone.utc).isoformat(),
            })
            # 审计标记（role=system，_build_messages 会 skip，仅供前端 UI 显示"已压缩"）
            await store.append_message(conv_id, {
                'role': 'system', 'name': 'compaction',
                'content': f'[compaction] 已压缩 {len(old)} 条早期消息',
                'timestamp': int(time.time() * 1000),
            })
        except Exception:
            logger.exception('failed to persist compaction for conversation %s', conv_id)

        # 返回当前请求用的内存消息：system + 历史摘要 + 近期原文
        new_messages: List[dict] = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'system', 'content': f'历史摘要：\n{summary}'},
        ]
        for m in recent:
            new_messages.append(self._build_llm_entry(m))
        return new_messages, summary

    @staticmethod
    def _split_window(
        messages: List[dict], keep_chars: int
    ) -> Tuple[List[dict], List[dict]]:
        """从末尾累积字符达到 keep_chars 作为近期窗口，其余为 old。

        保证：近期窗口至少 2 条消息；tool_call/tool 配对完整（近期不以 tool 开头）。
        """
        if not messages:
            return [], []
        acc = 0
        split_idx = 0
        for i in range(len(messages) - 1, -1, -1):
            acc += len(messages[i].get('content') or '')
            if acc >= keep_chars:
                split_idx = i
                break
        else:
            # 全部加起来都不够 keep_chars → 无法压缩
            return messages, []
        # 至少保留最后 2 条（避免吃掉当前轮上下文）
        split_idx = min(split_idx, len(messages) - 2)
        if split_idx < 0:
            split_idx = 0
        recent = messages[split_idx:]
        old = messages[:split_idx]
        # 保持 tool_call/tool 配对：近期若以 tool 开头，回拉前导 assistant(tool_calls)
        while old and recent and recent[0].get('role') == 'tool':
            recent.insert(0, old.pop())
        return recent, old

    async def _summarize(
        self, existing_summary: Optional[str], old_msgs: List[dict], provider: dict,
    ) -> str:
        """用 llm_stream 做轻量摘要（不带工具）。失败时降级为截断提示，不阻塞主流程。"""
        try:
            from agent_modules.agent_core.llm_stream import llm_stream
            transcript = self._serialize_for_summary(existing_summary, old_msgs)
            summary_messages = [
                {
                    'role': 'system',
                    'content': (
                        '你是对话摘要助手。将以下对话历史压缩为简洁摘要，保留：'
                        '用户意图、已完成的关键操作、关键文件路径。用中文，不超过 500 字。'
                    ),
                },
                {'role': 'user', 'content': transcript},
            ]
            parts: List[str] = []
            async for event in llm_stream(
                provider=provider,
                model_id=self._agent._model_id or '',
                messages=summary_messages,
                tools=None,
                temperature=0.3,
                max_tokens=1024,
                tool_choice=None,
                http_client=self._agent.http_client,
            ):
                if event.get('type') == 'delta':
                    parts.append(event.get('delta', ''))
            summary = ''.join(parts).strip()
            return summary or self._fallback_summary(existing_summary)
        except Exception:
            logger.exception('summarization failed; falling back to truncation notice')
            return self._fallback_summary(existing_summary)

    @staticmethod
    def _fallback_summary(existing_summary: Optional[str]) -> str:
        if existing_summary:
            return existing_summary + '\n（追加压缩摘要生成失败，早期对话已截断）'
        return '（早期对话摘要生成失败，已截断早期对话）'

    @staticmethod
    def _serialize_for_summary(
        existing_summary: Optional[str], msgs: List[dict]
    ) -> str:
        """把历史消息序列化为摘要用的文本。"""
        lines: List[str] = []
        if existing_summary:
            lines.append(f'[此前摘要] {existing_summary}')
        for m in msgs:
            role = m.get('role', '?')
            content = (m.get('content') or '').strip()
            if m.get('tool_calls'):
                names = [tc.get('function', {}).get('name', '') for tc in m['tool_calls']]
                content = f'[调用工具: {", ".join(names)}] ' + content
            if content:
                lines.append(f'{role}: {content[:500]}')
        return '\n'.join(lines)

    @staticmethod
    def _build_llm_entry(msg: dict) -> dict:
        """从存储消息构建 LLM 消息条目（不含 seq 等内部字段）。"""
        entry: dict = {'role': msg['role'], 'content': msg.get('content')}
        if msg.get('tool_calls'):
            entry['tool_calls'] = msg['tool_calls']
        if msg.get('tool_call_id'):
            entry['tool_call_id'] = msg['tool_call_id']
        if msg.get('name'):
            entry['name'] = msg['name']
        return entry
