import os
import json
import logging
from quart import Blueprint, jsonify
from zaowu_paths import get_project_root

log_bp = Blueprint('log', __name__)

BASE_DIR = get_project_root()
LOG_FILE = os.path.join(BASE_DIR, 'log.json')

_logger = logging.getLogger('zaowu.routes.log')


def append_log(entry):
    """追加一条日志到 log.json（双写：JSON 文件 + logging 管道）。

    保留 JSON 文件写入以兼容前端 GET /api/log 读取；
    同时通过 logging 管道写入以兼容 RotatingFileHandler。
    """
    log_entry = {
        'timestamp': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        'level': entry.get('level', 'error'),
        'type': entry.get('type', 'UnknownError'),
        'message': entry.get('message', ''),
    }
    if 'details' in entry:
        log_entry['details'] = entry['details']

    # 1) 原有 JSON 文件写入（保持前端兼容）
    try:
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                logs = json.load(f).get('logs', [])
        logs.append(log_entry)
        tmp = LOG_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'logs': logs}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, LOG_FILE)
    except Exception:
        pass

    # 2) 同步写入 logging 管道（RotatingFileHandler → log.json JSON Lines）
    try:
        level = getattr(logging, entry.get('level', 'error').upper(), logging.ERROR)
        extra_fields = {
            'error_type': entry.get('type', 'UnknownError'),
        }
        if 'details' in entry:
            extra_fields['extra_details'] = entry['details']
        _logger.log(level, entry.get('message', ''), extra=extra_fields)
    except Exception:
        pass


@log_bp.route('', methods=['GET'])
def get_logs():
    if not os.path.exists(LOG_FILE):
        return jsonify({'logs': []})
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return jsonify({'logs': data.get('logs', [])})
    except (json.JSONDecodeError, IOError):
        return jsonify({'logs': []})
