import os
import json
import uuid
import shutil
import stat
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

explorer_bp = Blueprint('explorer', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_FILE = os.path.join(BASE_DIR, 'projects.json')

_project_lock = __import__('threading').Lock()


def read_projects():
    with _project_lock:
        if not os.path.exists(PROJECTS_FILE):
            return []
        try:
            with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('projects', [])
        except (json.JSONDecodeError, IOError):
            return []


def write_projects(projects):
    with _project_lock:
        tmp = PROJECTS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'projects': projects}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROJECTS_FILE)


def validate_projects():
    projects = read_projects()
    valid = []
    for p in projects:
        zaowu_path = os.path.join(p['path'], '.zaowu')
        if os.path.exists(zaowu_path):
            valid.append(p)
    if len(valid) != len(projects):
        write_projects(valid)
    return valid


def read_zaowu(project_path):
    zaowu_path = os.path.join(project_path, '.zaowu')
    if not os.path.exists(zaowu_path):
        return None
    try:
        with open(zaowu_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def write_zaowu(project_path, data):
    zaowu_path = os.path.join(project_path, '.zaowu')
    with open(zaowu_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_project(project_id):
    projects = read_projects()
    for p in projects:
        if p['id'] == project_id:
            return p
    return None


def validate_path(path):
    real = os.path.realpath(path)
    if not os.path.exists(real):
        return None
    return real


def get_folder_name(path):
    return os.path.basename(path.rstrip(os.sep))


def get_last_modified(path):
    try:
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def log_error(msg, details=None):
    log_path = os.path.join(BASE_DIR, 'log.json')
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'level': 'error',
        'type': 'OperationError',
        'message': msg,
    }
    if details:
        entry['details'] = details
    try:
        logs = []
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                logs = json.load(f).get('logs', [])
        logs.append(entry)
        tmp = log_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'logs': logs}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, log_path)
    except Exception:
        pass


def is_binary_file(filepath):
    binary_exts = {
        '.exe', '.dll', '.so', '.dylib', '.bin', '.dat', '.pdb', '.obj', '.o', '.a', '.lib',
        '.class', '.pyc', '.pyo', '.jar', '.war', '.ear',
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svg', '.tiff', '.psd', '.ai',
        '.mp3', '.wav', '.ogg', '.flac', '.aac', '.wma', '.m4a',
        '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.mpg', '.mpeg',
        '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.zst',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.ttf', '.otf', '.woff', '.woff2', '.eot',
        '.iso', '.img', '.vhd', '.vmdk', '.ova',
    }
    _, ext = os.path.splitext(filepath)
    return ext.lower() in binary_exts


@explorer_bp.route('/projects', methods=['GET'])
def get_projects():
    projects = read_projects()
    result = []
    for p in projects:
        zaowu = read_zaowu(p['path'])
        name = zaowu['name'] if zaowu and 'name' in zaowu else get_folder_name(p['path'])
        archived = zaowu.get('archived', False) if zaowu else False
        last_modified = get_last_modified(p['path'])
        result.append({
            'id': p['id'],
            'path': p['path'],
            'name': name,
            'addedAt': p.get('addedAt'),
            'archived': archived,
            'lastModified': last_modified,
        })
    return jsonify({'projects': result})


@explorer_bp.route('/add-project', methods=['POST'])
def add_project():
    data = request.get_json(silent=True)
    if not data or 'path' not in data:
        return jsonify({'ok': False, 'error': 'missing path'}), 400

    path = validate_path(data['path'])
    if not path:
        return jsonify({'ok': False, 'error': 'invalid path'}), 400

    projects = read_projects()
    for p in projects:
        if os.path.realpath(p['path']) == path:
            return jsonify({'ok': False, 'error': 'duplicate project'}), 409

    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    name = get_folder_name(path)

    zaowu_data = {
        'id': project_id,
        'name': name,
        'addedAt': now,
        'archived': False,
    }
    try:
        write_zaowu(path, zaowu_data)
    except Exception as e:
        log_error('Failed to create .zaowu', {'path': path, 'error': str(e)})
        return jsonify({'ok': False, 'error': 'cannot create .zaowu'}), 500

    new_project = {'id': project_id, 'path': path, 'addedAt': now}
    projects.append(new_project)
    write_projects(projects)

    return jsonify({
        'ok': True,
        'project': {
            'id': project_id,
            'path': path,
            'name': name,
            'addedAt': now,
            'archived': False,
            'lastModified': get_last_modified(path),
        }
    })


@explorer_bp.route('/archive-project', methods=['POST'])
def archive_project():
    data = request.get_json(silent=True)
    if not data or 'projectId' not in data:
        return jsonify({'ok': False, 'error': 'missing projectId'}), 400

    project = find_project(data['projectId'])
    if not project:
        return jsonify({'ok': False, 'error': 'project not found'}), 404

    zaowu = read_zaowu(project['path'])
    if zaowu:
        zaowu['archived'] = True
        write_zaowu(project['path'], zaowu)
    return jsonify({'ok': True})


@explorer_bp.route('/unarchive-project', methods=['POST'])
def unarchive_project():
    data = request.get_json(silent=True)
    if not data or 'projectId' not in data:
        return jsonify({'ok': False, 'error': 'missing projectId'}), 400

    project = find_project(data['projectId'])
    if not project:
        return jsonify({'ok': False, 'error': 'project not found'}), 404

    zaowu = read_zaowu(project['path'])
    if zaowu:
        zaowu['archived'] = False
        write_zaowu(project['path'], zaowu)
    return jsonify({'ok': True})


@explorer_bp.route('/unload-project', methods=['POST'])
def unload_project():
    data = request.get_json(silent=True)
    if not data or 'projectId' not in data:
        return jsonify({'ok': False, 'error': 'missing projectId'}), 400

    project = find_project(data['projectId'])
    if not project:
        return jsonify({'ok': False, 'error': 'project not found'}), 404

    zaowu_path = os.path.join(project['path'], '.zaowu')
    try:
        if os.path.exists(zaowu_path):
            os.remove(zaowu_path)
    except Exception as e:
        log_error('Failed to remove .zaowu', {'path': zaowu_path, 'error': str(e)})

    projects = read_projects()
    projects = [p for p in projects if p['id'] != data['projectId']]
    write_projects(projects)
    return jsonify({'ok': True})


@explorer_bp.route('/delete-project', methods=['POST'])
def delete_project():
    data = request.get_json(silent=True)
    if not data or 'projectId' not in data:
        return jsonify({'ok': False, 'error': 'missing projectId'}), 400

    project = find_project(data['projectId'])
    if not project:
        return jsonify({'ok': False, 'error': 'project not found'}), 404

    zaowu_path = os.path.join(project['path'], '.zaowu')
    try:
        if os.path.exists(zaowu_path):
            os.remove(zaowu_path)
    except Exception as e:
        log_error('Failed to remove .zaowu', {'path': zaowu_path, 'error': str(e)})

    projects = read_projects()
    projects = [p for p in projects if p['id'] != data['projectId']]
    write_projects(projects)

    try:
        send2trash = None
        try:
            from send2trash import send2trash as s2t
            send2trash = s2t
        except ImportError:
            pass

        if send2trash:
            send2trash(project['path'])
        else:
            if os.path.isdir(project['path']):
                shutil.rmtree(project['path'])
            else:
                os.remove(project['path'])
    except Exception as e:
        log_error('Failed to delete project folder', {'path': project['path'], 'error': str(e)})
        return jsonify({'ok': False, 'error': 'failed to delete folder'}), 500

    return jsonify({'ok': True})


@explorer_bp.route('/batch-archive', methods=['POST'])
def batch_archive():
    return _batch_operation('archive')


@explorer_bp.route('/batch-unload', methods=['POST'])
def batch_unload():
    return _batch_operation('unload')


@explorer_bp.route('/batch-delete', methods=['POST'])
def batch_delete():
    return _batch_operation('delete')


def _batch_operation(op_type):
    data = request.get_json(silent=True)
    if not data or 'projectIds' not in data:
        return jsonify({'ok': False, 'error': 'missing projectIds'}), 400

    project_ids = data['projectIds']
    results = []
    projects = read_projects()

    for pid in project_ids:
        project = next((p for p in projects if p['id'] == pid), None)
        if not project:
            results.append({'id': pid, 'ok': False, 'error': 'not found'})
            continue

        try:
            if op_type == 'archive':
                zaowu = read_zaowu(project['path'])
                if zaowu:
                    zaowu['archived'] = True
                    write_zaowu(project['path'], zaowu)
                results.append({'id': pid, 'ok': True})
            elif op_type == 'unload':
                zaowu_path = os.path.join(project['path'], '.zaowu')
                if os.path.exists(zaowu_path):
                    os.remove(zaowu_path)
                projects = [p for p in projects if p['id'] != pid]
                results.append({'id': pid, 'ok': True})
            elif op_type == 'delete':
                zaowu_path = os.path.join(project['path'], '.zaowu')
                if os.path.exists(zaowu_path):
                    os.remove(zaowu_path)
                projects = [p for p in projects if p['id'] != pid]
                try:
                    send2trash = None
                    try:
                        from send2trash import send2trash as s2t
                        send2trash = s2t
                    except ImportError:
                        pass
                    if send2trash:
                        send2trash(project['path'])
                    else:
                        if os.path.isdir(project['path']):
                            shutil.rmtree(project['path'])
                        else:
                            os.remove(project['path'])
                except Exception as e:
                    log_error('Failed to delete project folder', {'path': project['path'], 'error': str(e)})
                results.append({'id': pid, 'ok': True})
        except Exception as e:
            log_error(f'Batch {op_type} failed', {'projectId': pid, 'error': str(e)})
            results.append({'id': pid, 'ok': False, 'error': str(e)})

    write_projects(projects)
    return jsonify({'ok': True, 'results': results})


@explorer_bp.route('/get-tree', methods=['POST'])
def get_tree():
    data = request.get_json(silent=True)
    if not data or 'path' not in data:
        return jsonify({'ok': False, 'error': 'missing path'}), 400

    path = os.path.realpath(data['path'])
    depth = data.get('depth', 1)

    if not os.path.isdir(path):
        return jsonify({'ok': False, 'error': 'not a directory'}), 400

    try:
        tree = _build_tree(path, depth)
        return jsonify({'ok': True, 'tree': tree})
    except PermissionError:
        return jsonify({'ok': False, 'error': 'permission denied'}), 403
    except Exception as e:
        log_error('Failed to read directory', {'path': path, 'error': str(e)})
        return jsonify({'ok': False, 'error': 'failed to read directory'}), 500


def _is_access_allowed(target_path, allowed_roots):
    target_real = os.path.realpath(target_path)
    for root in allowed_roots:
        root_real = os.path.realpath(root)
        if target_real == root_real or target_real.startswith(root_real + os.sep):
            return True
    return False


@explorer_bp.route('/read-file', methods=['GET'])
def read_file():
    path = request.args.get('path', '')
    if not path:
        return jsonify({'ok': False, 'error': 'missing path'}), 400

    real = os.path.realpath(path)
    if not os.path.isfile(real):
        return jsonify({'ok': False, 'error': 'not a file'}), 400

    if is_binary_file(real):
        return jsonify({'ok': False, 'error': 'binary file'}), 400

    try:
        size = os.path.getsize(real)
        if size > 1024 * 1024:
            return jsonify({'ok': False, 'error': 'file too large'}), 400

        with open(real, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({'ok': True, 'content': content, 'size': size})
    except UnicodeDecodeError:
        return jsonify({'ok': False, 'error': 'encoding error'}), 400
    except PermissionError:
        return jsonify({'ok': False, 'error': 'permission denied'}), 403
    except Exception as e:
        log_error('Failed to read file', {'path': path, 'error': str(e)})
        return jsonify({'ok': False, 'error': 'failed to read file'}), 500


@explorer_bp.route('/save-file', methods=['POST'])
def save_file():
    data = request.get_json(silent=True)
    if not data or 'path' not in data or 'content' not in data:
        return jsonify({'ok': False, 'error': 'missing path or content'}), 400

    real = os.path.realpath(data['path'])
    if not os.path.isfile(real):
        return jsonify({'ok': False, 'error': 'not a file'}), 400

    try:
        with open(real, 'w', encoding='utf-8') as f:
            f.write(data['content'])
        return jsonify({'ok': True})
    except PermissionError:
        return jsonify({'ok': False, 'error': 'permission denied'}), 403
    except Exception as e:
        log_error('Failed to save file', {'path': data['path'], 'error': str(e)})
        return jsonify({'ok': False, 'error': 'failed to save file'}), 500


def _build_tree(dir_path, depth):
    tree = []
    try:
        entries = sorted(os.scandir(dir_path), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
    except PermissionError:
        return tree

    for entry in entries:
        if entry.name.startswith('.'):
            continue
        node = {
            'name': entry.name,
            'path': entry.path,
            'type': 'directory' if entry.is_dir(follow_symlinks=False) else 'file',
        }
        if entry.is_dir(follow_symlinks=False) and depth > 0:
            if depth > 1:
                node['children'] = _build_tree(entry.path, depth - 1)
        tree.append(node)

    return tree
