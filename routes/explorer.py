import os
import json
import uuid
import shutil
import stat
import asyncio
import logging
from datetime import datetime, timezone
from quart import Blueprint, request, jsonify

from plugin_system import get_plugin_manager

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


_explorer_logger = logging.getLogger('zaowu.routes.explorer')


def log_error(msg, details=None):
    """记录操作错误（委托给统一 logging 系统）。
    
    生成的日志会通过 JsonLogFormatter 写入 log.json，
    同时通过 StreamHandler 输出到 console。
    """
    extra = {'error_type': details.get('type', 'OperationError')} if details else {}
    _explorer_logger.error(msg, extra=extra, stack_info=False)


def is_binary_file(filepath):
    from services.file_utils import is_binary_file as _check
    return _check(filepath)


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
async def add_project():
    data = await request.get_json(silent=True)
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
async def archive_project():
    data = await request.get_json(silent=True)
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
async def unarchive_project():
    data = await request.get_json(silent=True)
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
async def unload_project():
    data = await request.get_json(silent=True)
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
async def delete_project():
    data = await request.get_json(silent=True)
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
async def batch_archive():
    return await _batch_operation('archive')


@explorer_bp.route('/batch-unload', methods=['POST'])
async def batch_unload():
    return await _batch_operation('unload')


@explorer_bp.route('/batch-delete', methods=['POST'])
async def batch_delete():
    return await _batch_operation('delete')


async def _batch_operation(op_type):
    data = await request.get_json(silent=True)
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
async def get_tree():
    data = await request.get_json(silent=True)
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


def _fire_file_hook(hook_name: str, *args) -> None:
    """异步触发文件系统事件 hook（fire-and-forget，不阻塞请求）。

    通过 PluginManager 中存储的主事件循环引用 _main_loop，使用
    call_soon_threadsafe() 从任意线程（包括 Quart 线程池中的同步路由）
    将协程投递到主事件循环执行。
    """
    mgr = get_plugin_manager()
    if mgr is None or not hasattr(mgr, '_main_loop') or mgr._main_loop is None:
        return

    async def _run_hooks():
        try:
            await mgr.fire_hook(hook_name, *args)
        except Exception:
            pass

    # fire-and-forget：从任意线程投递到主事件循环
    mgr._main_loop.call_soon_threadsafe(
        lambda: asyncio.ensure_future(_run_hooks(), loop=mgr._main_loop)
    )


@explorer_bp.route('/save-file', methods=['POST'])
async def save_file():
    data = await request.get_json(silent=True)
    if not data or 'path' not in data or 'content' not in data:
        return jsonify({'ok': False, 'error': 'missing path or content'}), 400

    real = os.path.realpath(data['path'])

    # v1.2 修正：允许创建新文件（仅限项目内路径）；原代码用 isfile 阻止了创建
    if not is_path_in_projects(real):
        return jsonify({'ok': False, 'error': 'path not in registered projects'}), 403

    parent = os.path.dirname(real)
    if not os.path.isdir(parent):
        return jsonify({'ok': False, 'error': 'parent directory does not exist'}), 400

    try:
        os.makedirs(parent, exist_ok=True)
        with open(real, 'w', encoding='utf-8') as f:
            f.write(data['content'])
        # 文件保存成功后触发插件 hook
        _fire_file_hook('zaowu_on_file_saved', real)
        return jsonify({'ok': True})
    except PermissionError:
        return jsonify({'ok': False, 'error': 'permission denied'}), 403
    except Exception as e:
        log_error('Failed to save file', {'path': data['path'], 'error': str(e)})
        return jsonify({'ok': False, 'error': 'failed to save file'}), 500


@explorer_bp.route('/delete-file', methods=['POST'])
async def delete_file():
    """删除单个文件。成功后触发 zaowu_on_file_deleted hook。"""
    data = await request.get_json(silent=True)
    if not data or 'path' not in data:
        return jsonify({'ok': False, 'error': 'missing path'}), 400

    real = os.path.realpath(data['path'])
    if not os.path.isfile(real):
        return jsonify({'ok': False, 'error': 'not a file'}), 400

    try:
        os.remove(real)
        _fire_file_hook('zaowu_on_file_deleted', real)
        return jsonify({'ok': True})
    except PermissionError:
        return jsonify({'ok': False, 'error': 'permission denied'}), 403
    except Exception as e:
        log_error('Failed to delete file', {'path': data['path'], 'error': str(e)})
        return jsonify({'ok': False, 'error': 'failed to delete file'}), 500


@explorer_bp.route('/rename-file', methods=['POST'])
async def rename_file():
    """重命名 / 移动单个文件。成功后触发 zaowu_on_file_renamed hook。"""
    data = await request.get_json(silent=True)
    if not data or 'oldPath' not in data or 'newPath' not in data:
        return jsonify({'ok': False, 'error': 'missing oldPath or newPath'}), 400

    old_real = os.path.realpath(data['oldPath'])
    new_real = os.path.realpath(data['newPath'])

    if not os.path.exists(old_real):
        return jsonify({'ok': False, 'error': 'source file not found'}), 400

    try:
        os.rename(old_real, new_real)
        _fire_file_hook('zaowu_on_file_renamed', old_real, new_real)
        return jsonify({'ok': True})
    except PermissionError:
        return jsonify({'ok': False, 'error': 'permission denied'}), 403
    except Exception as e:
        log_error('Failed to rename file', {'oldPath': data['oldPath'], 'newPath': data['newPath'], 'error': str(e)})
        return jsonify({'ok': False, 'error': 'failed to rename file'}), 500


def is_path_in_projects(target_path):
    """检查路径是否属于已注册的项目路径范围内"""
    real_target = os.path.realpath(target_path)
    projects = read_projects()
    for p in projects:
        real_root = os.path.realpath(p['path'])
        if real_target == real_root or real_target.startswith(real_root + os.sep):
            return True
    return False


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
