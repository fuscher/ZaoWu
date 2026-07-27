from __future__ import annotations

import json
import os
import random
import string
from datetime import datetime
from workflow_engine.nodes.base import BaseNode
from workflow_engine.sse_helpers import _sse_node_started, _sse_node_ended
from zaowu_paths import get_project_root


class EndNode(BaseNode):
    node_type = 'end'

    async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
        yield _sse_node_started(ctx, ctx_node)

        raw = ctx_node.inputs.get('default', [])
        if not isinstance(raw, list):
            raw = [raw]

        end_mode = self.config.get('endMode', 'log')

        if end_mode == 'none':
            ctx_node.outputs = {'default': ''}
            yield _sse_node_ended(ctx, ctx_node)
            return

        # log 模式（默认）
        log_dir = self.config.get('logDir', './workflow_logs')
        log_format = self.config.get('logFormat', 'txt')
        custom_name = self.config.get('logName', '')

        base_dir = get_project_root()
        if not os.path.isabs(log_dir):
            log_dir = os.path.join(base_dir, log_dir)

        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            ctx_node.error = f'无法创建日志目录: {log_dir}'
            ctx_node.outputs = {'default': raw}
            yield _sse_node_ended(ctx, ctx_node)
            return

        ext = {'json': 'json', 'markdown': 'md', 'txt': 'txt'}.get(log_format, 'txt')

        if custom_name:
            filename = f'{custom_name}.{ext}'
        else:
            ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
            wf_name = ctx.definition.name if ctx.definition else 'workflow'
            filename = f'{ts}_{wf_name}_{rand}.{ext}'

        filepath = os.path.join(log_dir, filename)

        try:
            if log_format == 'json':
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
            elif log_format == 'markdown':
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(_format_as_markdown(raw))
            else:  # txt
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(_format_as_text(raw))
        except OSError as e:
            ctx_node.error = f'写入日志文件失败: {e}'
            ctx_node.outputs = {'default': raw}
            yield _sse_node_ended(ctx, ctx_node)
            return

        ctx_node.outputs = {'default': f'结果已保存: {filename}'}
        yield _sse_node_ended(ctx, ctx_node)


def _format_as_text(raw: list) -> str:
    return '\n---\n'.join(str(item) for item in raw)


def _format_as_markdown(raw: list) -> str:
    lines = ['# 工作流输出\n']
    for i, item in enumerate(raw):
        lines.append(f'## 输出 {i + 1}\n')
        lines.append(str(item))
        lines.append('')
    return '\n'.join(lines)
