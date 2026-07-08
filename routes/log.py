import os
import json
from flask import Blueprint, jsonify

log_bp = Blueprint('log', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, 'log.json')


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
