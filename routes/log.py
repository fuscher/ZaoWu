import os
import json
from flask import Blueprint, jsonify

log_bp = Blueprint('log', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, 'log.json')


def append_log(entry):
    """追加一条日志到 log.json"""
    log_entry = {
        'timestamp': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        'level': entry.get('level', 'error'),
        'type': entry.get('type', 'UnknownError'),
        'message': entry.get('message', ''),
    }
    if 'details' in entry:
        log_entry['details'] = entry['details']
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
