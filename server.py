import os
import json
import locale
from flask import Flask, send_from_directory, request, jsonify
from routes import explorer_bp, search_bp, log_bp, chat_bp, git_bp, terminal_bp, community_bp

app = Flask(__name__)


def _run_gevent_server(port):
    import sys
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    
    class CustomWebSocketHandler(WebSocketHandler):
        def run_websocket(self):
            path = self.environ.get('PATH_INFO', '')
            if path.startswith('/api/community/ws/'):
                self.handle_community_websocket()
            else:
                super().run_websocket()
        
        def handle_community_websocket(self):
            """Authentication + connection setup, delegates to shared message loop."""
            from services import room_service
            from collaboration.room import get_collab_room
            from collaboration.ws_server import run_message_loop

            path = self.environ.get('PATH_INFO', '')
            room_id = path.replace('/api/community/ws/', '')

            query_string = self.environ.get('QUERY_STRING', '')
            token = ''
            for part in query_string.split('&'):
                if part.startswith('token='):
                    token = part[6:]

            session = room_service.validate_token(token)
            if not session or session['room_id'] != room_id:
                return

            user_id = session['user_id']
            if not room_service.get_user(room_id, user_id):
                return

            get_collab_room(room_id).add_connection(user_id, self.websocket)
            room_service.set_user_status(room_id, user_id, 'online')

            run_message_loop(self.websocket, room_id, user_id)
    
    server = pywsgi.WSGIServer(('0.0.0.0', port), app, handler_class=CustomWebSocketHandler)
    server.serve_forever()

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
    'communityMaxUsers': 5,
    'communityDefaultRole': 'collaborator',
    'communityFileSizeLimitKB': 512,
    'communityInactiveTimeoutMinutes': 120,
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
app.register_blueprint(community_bp, url_prefix='/api/community')


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


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


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
    try:
        _run_gevent_server(port)
    except Exception:
        # Fallback to Flask development server if gevent is unavailable
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == '__main__':
    run_server()
