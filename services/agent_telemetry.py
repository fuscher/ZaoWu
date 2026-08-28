"""Agent 运行遥测 — 轻量聚合（S13-P1-2）。

每次 Agent 运行产生一行 JSON append 到 ``logs/agent_telemetry.ndjson``
（JSON Lines 格式，与 ``logging_config.py`` 的 ``logs/app.ndjson`` 同目录
同风格；文件不存在自动创建）。写入失败**不阻断主流程**：
调用方（agent_service.process_message finally）自行 try/except，
此处仅保证单行原子追加。

字段（由调用方聚合后传入）：
- ``ts``：ISO8601 时间戳（默认当前时刻，可覆盖）
- ``conv_id`` / ``model``：会话与模型标识
- ``tokens_in`` / ``tokens_out``：本轮累计 usage（``_stream_llm`` 消费 usage 事件）
- ``tool_count``：实际执行的工具调用次数
- ``iterations``：主循环迭代轮数
- ``quality``：完成质量（success/idle/constrained/empty/stopped/
  error_fallback/incomplete）
- ``error_code``：错误分类码（如有）
- ``duration_ms``：process_message 入口到 finally 收尾的 wall-clock 时长
  （含 LLM 调用 + 工具执行 + 审批等待）
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from zaowu_paths import get_project_root

LOG_DIR = os.path.join(get_project_root(), 'logs')
TELEMETRY_FILE = os.path.join(LOG_DIR, 'agent_telemetry.ndjson')

# 预置字段默认值：调用方未提供时补缺省（None → 不写入该键，保持行紧凑）
_DEFAULTS: Dict[str, Any] = {
    'conv_id': None, 'model': None,
    'tokens_in': 0, 'tokens_out': 0,
    'tool_count': 0, 'iterations': 0,
    'quality': None, 'error_code': None,
    'duration_ms': None,
}


def record_agent_run(**fields: Optional[Any]) -> None:
    """追加一条 Agent 运行遥测记录（JSON Lines）。

    缺失字段按缺省值补全；值为 None 的键不写入（避免 null 噪声）。
    失败（目录不可写等）由调用方捕获，本函数不吞异常。
    """
    entry: Dict[str, Any] = {'ts': datetime.now(timezone.utc).isoformat()}
    for key, default in _DEFAULTS.items():
        value = fields.get(key, default)
        if value is not None:
            entry[key] = value
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(TELEMETRY_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
