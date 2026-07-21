"""统一日志配置 — 所有模块的日志同时输出到 console 和 logs/app.ndjson。

前端日志面板通过 GET /api/log 读取 log.json（append_log 维护的数组格式）；
本模块的 RotatingFileHandler 写入独立的 logs/app.ndjson（JSON Lines 格式），
避免与 log.json 的 {"logs":[...]} 结构产生格式冲突。

用法：
    在 server_quart.py 的 before_serving 阶段调用 configure_logging()，
    之后所有 logging.getLogger('zaowu.*') 的日志会自动写入 logs/app.ndjson。
"""

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from zaowu_paths import get_project_root

BASE_DIR = get_project_root()
LOG_FILE = os.path.join(BASE_DIR, 'logs', 'app.ndjson')

MAX_LOG_SIZE = 2 * 1024 * 1024   # 2MB 滚动
BACKUP_COUNT = 3


# ── JSON Lines 格式 ───────────────────────────────────────────────

class JsonLogFormatter(logging.Formatter):
    """将 LogRecord 格式化为 JSON Lines（每行一个完整 JSON 对象）。

    产出格式::
        {"timestamp":"2026-01-01T00:00:00.000Z","level":"error",
         "type":"GitOperationError","message":"说明文字","details":{...}}
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname.lower(),
            'type': getattr(record, 'error_type', record.name),
            'message': record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry['details'] = {
                'exception': str(record.exc_info[1]),
                'module': record.pathname,
                'line': record.lineno,
            }
        # 支持显式传入 details（如 routes/git.py 的 append_log 调用）
        extra_details = getattr(record, 'extra_details', None)
        if extra_details:
            entry.setdefault('details', {}).update(extra_details)
        return json.dumps(entry, ensure_ascii=False)


# ── 初始化 ────────────────────────────────────────────────────────

def configure_logging() -> logging.Logger:
    """初始化 app 级日志配置。

    返回 zaowu 命名空间的 root logger，所有 getLogger('zaowu.*') 自动继承
    FileHandler（→ logs/app.ndjson）+ StreamHandler（→ console）。
    """
    root = logging.getLogger('zaowu')
    if root.handlers:
        return root   # 已配置，幂等

    root.setLevel(logging.INFO)

    # File handler → logs/app.ndjson（JSON Lines，独立于 log.json）
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    fh = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8',
    )
    fh.setFormatter(JsonLogFormatter())
    root.addHandler(fh)

    # Console handler（开发调试用）
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    ))
    root.addHandler(ch)

    return root
