import os
import json
import threading
import uuid
from quart import Blueprint, request, jsonify

search_bp = Blueprint('search', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')

_search_events = {}
_search_lock = threading.Lock()


def _read_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _read_projects():
    projects_file = os.path.join(BASE_DIR, 'projects.json')
    if not os.path.exists(projects_file):
        return []
    try:
        with open(projects_file, 'r', encoding='utf-8') as f:
            return json.load(f).get('projects', [])
    except (json.JSONDecodeError, IOError):
        return []


def _is_archived(project_path):
    zaowu_path = os.path.join(project_path, '.zaowu')
    if not os.path.exists(zaowu_path):
        return False
    try:
        with open(zaowu_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('archived', False)
    except (json.JSONDecodeError, IOError):
        return False


from services.file_utils import is_binary_file as _is_binary


def _search_in_file(filepath, query_lower, max_file_size_kb):
    matches = []
    try:
        size_kb = os.path.getsize(filepath) / 1024
        if size_kb > max_file_size_kb:
            return matches
    except OSError:
        return matches

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                lower_line = line.lower()
                start = 0
                while True:
                    idx = lower_line.find(query_lower, start)
                    if idx == -1:
                        break
                    matches.append({
                        'type': 'content',
                        'line': line_num,
                        'content': line.rstrip('\n\r'),
                        'startIndex': idx,
                        'endIndex': idx + len(query_lower),
                    })
                    start = idx + 1
                    if len(matches) >= 50:
                        return matches
    except (OSError, UnicodeDecodeError):
        pass
    return matches


@search_bp.route('', methods=['POST'])
async def search():
    data = await request.get_json(silent=True)
    if not data or 'query' not in data:
        return jsonify({'ok': False, 'error': 'missing query'}), 400

    query = data['query'].strip()
    if not query:
        return jsonify({'ok': True, 'results': [], 'totalFiles': 0, 'totalMatches': 0})

    settings = _read_settings()
    max_file_size_kb = settings.get('searchMaxFileSizeKB', 1024)
    result_limit = settings.get('searchResultLimit', 500)

    request_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    with _search_lock:
        _search_events[request_id] = cancel_event

    projects = _read_projects()
    active_projects = [p for p in projects if not _is_archived(p.get('path', ''))]

    # Append virtual (collaboration) project paths
    try:
        from community_ws import _room_project_paths
        for vid, vpath in _room_project_paths.items():
            if os.path.isdir(vpath):
                active_projects.append({'id': vid, 'path': vpath})
    except ImportError:
        pass

    results = []
    total_files = 0
    total_matches = 0
    query_lower = query.lower()

    try:
        for project in active_projects:
            project_path = project.get('path', '')
            if not os.path.isdir(project_path):
                continue

            for root, dirs, files in os.walk(project_path):
                if cancel_event.is_set():
                    break

                dirs[:] = [d for d in dirs if not d.startswith('.')]

                for filename in files:
                    if cancel_event.is_set():
                        break

                    filepath = os.path.join(root, filename)

                    if _is_binary(filepath):
                        continue

                    file_matches = []
                    lower_name = filename.lower()
                    if query_lower in lower_name:
                        file_matches.append({'type': 'filename'})

                    content_matches = _search_in_file(filepath, query_lower, max_file_size_kb)
                    file_matches.extend(content_matches)

                    if file_matches:
                        total_files += 1
                        total_matches += len(file_matches)
                        results.append({
                            'path': filepath,
                            'name': filename,
                            'matches': file_matches,
                        })

                        if total_matches >= result_limit:
                            break

                if total_matches >= result_limit:
                    break

            if cancel_event.is_set() or total_matches >= result_limit:
                break
    finally:
        with _search_lock:
            _search_events.pop(request_id, None)

    return jsonify({
        'ok': True,
        'results': results,
        'totalFiles': total_files,
        'totalMatches': total_matches,
    })


@search_bp.route('/cancel', methods=['POST'])
def cancel_search():
    with _search_lock:
        for event in _search_events.values():
            event.set()
    return jsonify({'ok': True})
