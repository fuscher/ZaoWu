import os
import json
import locale
from flask import Flask, send_from_directory, request, jsonify
from routes import explorer_bp, search_bp, log_bp, chat_bp, git_bp, terminal_bp

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
    'searchMaxFileSizeKB': 1024,
    'searchResultLimit': 500,
}


def detect_language():
    try:
        system_lang = locale.getdefaultlocale()[0]
    except Exception:
        system_lang = None
    if system_lang and system_lang.startswith('zh'):
        return 'zh-CN'
    return 'en'


def read_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if 'language' not in saved:
                    saved['language'] = detect_language()
                for key, val in DEFAULTS.items():
                    if key not in saved:
                        saved[key] = val
                return saved
        except (json.JSONDecodeError, IOError):
            pass
    return {**DEFAULTS, 'language': detect_language()}


def write_settings(data):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


app.register_blueprint(explorer_bp, url_prefix='/api/explorer')
app.register_blueprint(search_bp, url_prefix='/api/search')
app.register_blueprint(log_bp, url_prefix='/api/log')
app.register_blueprint(chat_bp, url_prefix='/api/chat')
app.register_blueprint(git_bp, url_prefix='/api/git')
app.register_blueprint(terminal_bp, url_prefix='/api/terminal')


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
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == '__main__':
    run_server()
