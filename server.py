import os
import json
from flask import Flask, send_from_directory, request, jsonify

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, 'ZaoWu', 'dist')
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')

DEFAULTS = {
    'enabled': True,
    'effect': 'linewaves',
    'persist': False,
    'language': 'zh-CN',
    'theme': 'dark',
}


def read_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {**DEFAULTS}


def write_settings(data):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.route('/')
def index():
    html_path = os.path.join(DIST_DIR, 'index.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    settings_json = json.dumps(read_settings())
    injected = html.replace(
        '<script ',
        f'<script>window.__SETTINGS__ = {settings_json};</script>\n    <script ',
        1,
    )
    return injected


@app.route('/assets/<path:path>')
def assets(path):
    return send_from_directory(os.path.join(DIST_DIR, 'assets'), path)


@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'GET':
        return jsonify(read_settings())
    elif request.method == 'POST':
        data = request.get_json(silent=True)
        if data and isinstance(data, dict):
            write_settings(data)
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'invalid data'}), 400


@app.route('/<path:path>')
def fallback(path):
    file_path = os.path.join(DIST_DIR, path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return send_from_directory(DIST_DIR, path)
    return send_from_directory(DIST_DIR, 'index.html')


def run_server(port=5000):
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)


if __name__ == '__main__':
    run_server()
