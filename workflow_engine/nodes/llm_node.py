from __future__ import annotations

import json
import os
import logging
import time
from workflow_engine.nodes.base import BaseNode
from workflow_engine.sse_helpers import _sse_node_started, _sse_node_progress, _sse_node_ended
from services.skill_registry import SkillRegistry
from zaowu_paths import get_project_root

logger = logging.getLogger(__name__)
PROVIDERS_FILE = os.path.join(get_project_root(), 'providers.json')


class LLMNode(BaseNode):
    node_type = 'llm'

    async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
        yield _sse_node_started(ctx, ctx_node)

        slots = self.config.get('slots') or {}
        model_config = slots.get('model') or {}
        prompt_config = slots.get('prompt') or {}
        skill_configs = slots.get('skills') or []

        provider = self._resolve_provider(model_config)
        model_id = model_config.get('modelId', '')
        prompt = ctx.resolve(prompt_config.get('template', '{{input}}'))

        messages = [{'role': 'system', 'content': self._build_system_prompt(slots)}]
        messages.append({'role': 'user', 'content': prompt})

        tools = self._build_tools_spec(skill_configs)
        tool_choice = 'auto' if tools else 'none'
        max_iterations = self.config.get('maxToolIterations', 10)
        loop_threshold = self.config.get('toolLoopThreshold', 3)

        from agent_modules.agent_core.llm_stream import llm_stream

        full_content = ''
        tool_call_parts: list[dict] = []
        # 死循环检测：记录最近的工具调用序列
        recent_tool_calls: list[str] = []
        start_time = time.time()

        for iteration in range(max_iterations):
            if stop_event and stop_event.is_set():
                break

            tool_call_parts.clear()

            async for part in llm_stream(
                provider=provider,
                model_id=model_id,
                messages=messages,
                tools=tools,
                temperature=model_config.get('temperature') or 0.7,
                max_tokens=model_config.get('maxTokens') or 4096,
                tool_choice=tool_choice,
                stop_event=stop_event,
            ):
                ptype = part['type']
                if ptype == 'delta':
                    full_content += part['delta']
                    yield _sse_node_progress(ctx, ctx_node, part['delta'])
                elif ptype == 'tool_call_part':
                    tool_call_parts.append(part['tool_call'])
                elif ptype == 'usage':
                    ctx_node.tokens_in += part.get('tokens_in', 0)
                    ctx_node.tokens_out += part.get('tokens_out', 0)

            # 无工具调用 → 结束循环
            if not tool_call_parts:
                break

            # 注入 assistant 消息（含 tool_calls）
            assistant_msg: dict = {'role': 'assistant', 'content': full_content}
            if tool_call_parts:
                assistant_msg['tool_calls'] = [
                    {
                        'id': tc['requestId'],
                        'type': 'function',
                        'function': {'name': tc['name'], 'arguments': json.dumps(tc['arguments'], ensure_ascii=False)},
                    }
                    for tc in tool_call_parts
                ]
            messages.append(assistant_msg)

            # LLM 可能在一次响应中要求多个工具调用；串行执行每个
            for tc in tool_call_parts:
                if stop_event and stop_event.is_set():
                    break

                tool_name = tc.get('name', '')
                tool_args = tc.get('arguments', {})
                request_id = tc.get('requestId', '')

                # 死循环检测
                sig = f'{tool_name}:{json.dumps(tool_args, ensure_ascii=False, sort_keys=True)}'
                recent_tool_calls.append(sig)
                if len(recent_tool_calls) > loop_threshold:
                    recent_tool_calls.pop(0)
                if recent_tool_calls.count(sig) >= loop_threshold:
                    tool_result = {
                        'role': 'tool',
                        'tool_call_id': request_id,
                        'content': json.dumps({
                            'success': False,
                            'error': f'检测到重复调用 {tool_name} 已达 {loop_threshold} 次，自动中断循环',
                            'tool': tool_name,
                        }, ensure_ascii=False),
                    }
                    messages.append(tool_result)
                    logger.warning('LLMNode %s 检测到死循环: %s', self.node_def.id, sig)
                    break

                # 危险工具确认
                from services.tool_executor import ToolExecutor
                from services.tool_registry import ToolRegistry
                registry = ToolRegistry.get_instance()
                executor = ToolExecutor(registry, ctx.project_paths)

                tool_def = registry.get(tool_name)
                requires_approval = tool_def.requires_approval if tool_def else False
                auto_approve = ctx.execution_config.auto_approve_writes

                if requires_approval and not (tool_name == 'write_file' and auto_approve):
                    from workflow_engine.sse_helpers import (
                        _sse_node_requires_confirmation, _sse_wf_paused, _sse_wf_resumed,
                    )
                    tool_call_payload = {
                        'requestId': f'{ctx.run_id}-{self.node_def.id}-{request_id}',
                        'name': tool_name,
                        'arguments': tool_args,
                    }
                    yield _sse_node_requires_confirmation(ctx, ctx_node, tool_call_payload)
                    yield _sse_wf_paused(ctx, 'tool_confirmation')
                    approved = await confirm_callback(self.node_def.id, tool_call_payload)
                    yield _sse_wf_resumed(ctx)
                    if not approved:
                        tool_result = {
                            'role': 'tool',
                            'tool_call_id': request_id,
                            'content': json.dumps({'success': False, 'error': '用户已拒绝'}, ensure_ascii=False),
                        }
                        messages.append(tool_result)
                        continue

                result = await executor.execute(tool_name, tool_args)
                tool_result = {
                    'role': 'tool',
                    'tool_call_id': request_id,
                    'content': json.dumps(result, ensure_ascii=False),
                }
                messages.append(tool_result)

            full_content = ''

        ctx_node.elapsed_ms = (time.time() - start_time) * 1000
        ctx_node.outputs = {
            'default': full_content,
            'tokens': ctx_node.tokens_in + ctx_node.tokens_out,
        }

        yield _sse_node_ended(ctx, ctx_node)

    def _resolve_provider(self, model_config: dict) -> dict:
        provider_id = model_config.get('providerId', '')
        try:
            with open(PROVIDERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return next((p for p in data.get('providers', []) if p['id'] == provider_id), {})
        except Exception:
            return {}

    def _build_system_prompt(self, slots: dict) -> str:
        prompt_config = slots.get('prompt') or {}
        system_prompt = prompt_config.get('systemPrompt', '') or ''
        registry = SkillRegistry.get_instance()
        for skill_cfg in (slots.get('skills') or []):
            skill_name = skill_cfg.get('skillName') if isinstance(skill_cfg, dict) else skill_cfg
            if not skill_name:
                continue
            skill = registry.get(skill_name)
            if skill and getattr(skill, 'system_prompt', ''):
                system_prompt += f"\n\n## Skill: {skill_name}\n\n{skill.system_prompt}"
        return system_prompt

    def _build_tools_spec(self, skill_configs: list) -> list:
        """根据注入的 skill 配置构建工具列表。
        收集所有已启用 skill 的 allowed_tools 白名单并集，
        通过 ToolRegistry 获取全局工具定义并使用 SkillSandbox 过滤。
        """
        registry = SkillRegistry.get_instance()
        from services.tool_registry import ToolRegistry
        tool_registry = ToolRegistry.get_instance()

        all_allowed: set[str] = set()
        has_any_skill = False
        for skill_cfg in (skill_configs or []):
            skill_name = skill_cfg.get('skillName') if isinstance(skill_cfg, dict) else skill_cfg
            if not skill_name:
                continue
            if not registry.is_enabled(skill_name):
                continue
            has_any_skill = True
            skill = registry.get(skill_name)
            if skill and skill.allowed_tools:
                all_allowed.update(skill.allowed_tools)

        if not has_any_skill:
            return []

        # 空白名单 → 放行全部工具
        if not all_allowed:
            return tool_registry.build_openai_tools_spec()

        # 按白名单过滤
        return [
            s for s in tool_registry.build_openai_tools_spec()
            if s.get('function', {}).get('name', '') in all_allowed
        ]
