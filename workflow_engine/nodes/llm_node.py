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

        # 延迟导入：避免 workflow_engine 模块加载时触发 agent_modules/agent_core/__init__
        # 导致 routes <-> workflow_engine 循环导入
        from agent_modules.agent_core.llm_stream import llm_stream

        full_content = ''
        tool_call_parts: list[dict] = []
        start_time = time.time()
        async for part in llm_stream(
            provider=provider,
            model_id=model_id,
            messages=messages,
            tools=tools,
            temperature=model_config.get('temperature') or 0.7,
            max_tokens=model_config.get('maxTokens') or 4096,
            tool_choice='none',
            stop_event=stop_event,
        ):
            ptype = part['type']
            if ptype == 'delta':
                full_content += part['delta']
                yield _sse_node_progress(ctx, ctx_node, part['delta'])
            elif ptype == 'tool_call_part':
                tool_call_parts.append(part['tool_call'])
            elif ptype == 'usage':
                ctx_node.tokens_in = part.get('tokens_in', 0)
                ctx_node.tokens_out = part.get('tokens_out', 0)

        if tool_call_parts:
            logger.warning(
                'LLMNode %s 在 tool_choice=none 下仍返回 %d 个工具调用，已忽略',
                self.node_def.id, len(tool_call_parts))

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
                system_prompt += f"\n\n## 技能：{skill_name}\n\n{skill.system_prompt}"
        return system_prompt

    def _build_tools_spec(self, skill_configs: list) -> list:
        return []
