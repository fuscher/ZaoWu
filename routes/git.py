import os
import shutil
import threading
import time
import traceback
from quart import Blueprint, request, jsonify
from routes.log import append_log
from routes.explorer import is_path_in_projects

git_bp = Blueprint('git', __name__)

_git_locks = {}
_git_locks_lock = threading.Lock()

RETRYABLE_OPS = {'check', 'status', 'branches', 'commits', 'init'}

# 默认受保护分支列表
DEFAULT_PROTECTED_BRANCHES = ['main', 'master']


def _get_protected_branches():
    """从配置文件读取受保护分支列表，未配置则返回默认值"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'config.json')
        if os.path.isfile(config_path):
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            return cfg.get('git', {}).get('protected_branches', DEFAULT_PROTECTED_BRANCHES)
    except Exception:
        pass
    return DEFAULT_PROTECTED_BRANCHES


def get_git_lock(path):
    with _git_locks_lock:
        real = os.path.realpath(path)
        if real not in _git_locks:
            _git_locks[real] = threading.Lock()
        return _git_locks[real]


def validate_git_path(path):
    if not path:
        return 'missing path'
    try:
        real = os.path.realpath(path)
        if not is_path_in_projects(real):
            return 'path is not within registered projects'
        return None
    except Exception as e:
        return str(e)


def _try_git_op(op_name, func, path):
    max_retries = 3 if op_name in RETRYABLE_OPS else 1
    last_error = None
    for attempt in range(max_retries):
        try:
            return func(), None
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                time.sleep(0.5)
    append_log({
        'level': 'error',
        'type': 'GitOperationError',
        'message': last_error,
        'details': {
            'operation': op_name,
            'path': path,
            'traceback': traceback.format_exc(),
        },
    })
    return None, last_error


def parse_status(raw):
    changes = []
    if not raw:
        return changes
    for line in raw.strip().split('\n'):
        if not line:
            continue
        if len(line) < 3:
            continue
        index_status = line[0]
        worktree_status = line[1]
        file_part = line[3:].strip()

        if index_status == '?':
            changes.append({'path': file_part, 'type': 'untracked', 'status': 'unstaged'})
            continue

        if index_status == 'R':
            parts = file_part.split(' -> ')
            old_path = parts[0] if len(parts) > 0 else ''
            new_path = parts[1] if len(parts) > 1 else file_part
            changes.append({
                'path': new_path, 'type': 'renamed', 'status': 'staged', 'oldPath': old_path,
            })
            continue

        if index_status in ('M', 'A', 'D'):
            type_map = {'M': 'modified', 'A': 'added', 'D': 'deleted'}
            changes.append({'path': file_part, 'type': type_map.get(index_status, 'modified'), 'status': 'staged'})

        if worktree_status in ('M', 'D'):
            type_map = {'M': 'modified', 'D': 'deleted'}
            changes.append({'path': file_part, 'type': type_map.get(worktree_status, 'modified'), 'status': 'unstaged'})
    return changes


def _get_remote_tip(repo):
    try:
        origin = repo.remotes.origin
        for ref in origin.refs:
            if ref.name == 'origin/' + repo.active_branch.name:
                return ref.commit.hexsha[:7]
    except Exception:
        pass
    return None


def format_commits(commits, local_tip, remote_tip):
    result = []
    for c in commits:
        result.append({
            'hash': c.hexsha,
            'shortHash': c.hexsha[:7],
            'message': c.message.strip().split('\n')[0] if c.message else '',
            'author': str(c.author),
            'date': c.committed_datetime.isoformat() if c.committed_datetime else '',
            'isLocalTip': c.hexsha[:7] == local_tip,
            'isRemoteTip': remote_tip is not None and c.hexsha[:7] == remote_tip,
        })
    return result


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@git_bp.route('/check', methods=['POST'])
def check_git():
    result, _ = _try_git_op('check', lambda: shutil.which('git') is not None, 'n/a')
    return jsonify({'available': bool(result)})


@git_bp.route('/status', methods=['POST'])
async def git_status():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import git as _git
    with get_git_lock(path):
        def _op():
            repo = _git.Repo(path)
            raw = repo.git.status('--porcelain')
            changes = parse_status(raw)
            return {
                'ok': True,
                'branch': repo.active_branch.name,
                'changes': changes,
                'hasRepo': True,
            }
        try:
            repo = _git.Repo(path)
            raw = repo.git.status('--porcelain')
            changes = parse_status(raw)
            return jsonify({
                'ok': True,
                'branch': repo.active_branch.name,
                'changes': changes,
                'hasRepo': True,
            })
        except _git.InvalidGitRepositoryError:
            return jsonify({'ok': True, 'hasRepo': False, 'changes': [], 'branch': ''})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'status', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/branches', methods=['POST'])
async def git_branches():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import git as _git
    with get_git_lock(path):
        def _op():
            repo = _git.Repo(path)
            current = repo.active_branch.name
            result = []
            for b in repo.branches:
                result.append({'name': b.name, 'isCurrent': b.name == current, 'isRemote': False})
            try:
                for ref in repo.remotes.origin.refs:
                    name = ref.name.split('/', 1)[1]
                    if name != 'HEAD' and not any(r['name'] == name and not r['isRemote'] for r in result):
                        result.append({'name': name, 'isCurrent': False, 'isRemote': True})
            except Exception:
                pass
            return {'ok': True, 'branches': result}
        result, err = _try_git_op('branches', _op, path)
        if err:
            return jsonify({'ok': False, 'error': err})
        return jsonify(result)


@git_bp.route('/switch-branch', methods=['POST'])
async def git_switch_branch():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    branch = data.get('branch', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if not branch or '/' in branch or '..' in branch:
        return jsonify({'ok': False, 'error': 'invalid branch name'}), 400

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            repo.git.checkout(branch)
            return jsonify({'ok': True})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'switch-branch', 'path': path, 'branch': branch,
                                    'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/commits', methods=['POST'])
async def git_commits():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    limit = data.get('limit', 20)
    offset = data.get('offset', 0)
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        return jsonify({'ok': False, 'error': 'limit must be 1-100'}), 400
    if not isinstance(offset, int) or offset < 0:
        return jsonify({'ok': False, 'error': 'offset cannot be negative'}), 400

    import git as _git
    with get_git_lock(path):
        def _op():
            repo = _git.Repo(path)
            commits = list(repo.iter_commits(max_count=limit, skip=offset))
            local_tip = repo.head.commit.hexsha[:7]
            remote_tip = _get_remote_tip(repo)
            formatted = format_commits(commits, local_tip, remote_tip)
            return {
                'ok': True,
                'commits': formatted,
                'localTip': local_tip,
                'remoteTip': remote_tip,
                'hasMore': len(commits) == limit,
            }
        result, err = _try_git_op('commits', _op, path)
        if err:
            return jsonify({'ok': False, 'error': err})
        return jsonify(result)


@git_bp.route('/stage', methods=['POST'])
async def git_stage():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    files = data.get('files', [])
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if not files or not isinstance(files, list):
        return jsonify({'ok': False, 'error': 'files list required'}), 400

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            repo.index.add(files)
            return jsonify({'ok': True})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'stage', 'path': path, 'files': files,
                                    'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/unstage', methods=['POST'])
async def git_unstage():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    files = data.get('files', [])
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if not files or not isinstance(files, list):
        return jsonify({'ok': False, 'error': 'files list required'}), 400

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            repo.git.reset('HEAD', '--', *files)
            return jsonify({'ok': True})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'unstage', 'path': path, 'files': files,
                                    'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/stage-all', methods=['POST'])
async def git_stage_all():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            repo.git.add('--all')
            return jsonify({'ok': True})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'stage-all', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/discard', methods=['POST'])
async def git_discard():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    files = data.get('files', [])
    include_untracked = data.get('includeUntracked', False)
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if not files or not isinstance(files, list):
        return jsonify({'ok': False, 'error': 'files list required'}), 400

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            # 区分已跟踪文件和未跟踪文件
            tracked = []
            untracked = []
            if include_untracked:
                raw = repo.git.status('--porcelain')
                untracked_set = set()
                for line in raw.strip().split('\n'):
                    if line.startswith('?? '):
                        untracked_set.add(line[3:].strip())
                for f in files:
                    (untracked if f in untracked_set else tracked).append(f)
            else:
                tracked = files

            # 已跟踪文件用 git checkout 还原
            if tracked:
                repo.git.checkout('--', *tracked)

            # 未跟踪文件直接删除（支持目录）
            for f in untracked:
                full = os.path.join(path, f)
                if os.path.isdir(full):
                    shutil.rmtree(full)
                elif os.path.isfile(full):
                    os.remove(full)

            return jsonify({'ok': True})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'discard', 'path': path, 'files': files,
                                    'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/commit', methods=['POST'])
async def git_commit():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    message = data.get('message', '')
    amend = data.get('amend', False)
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    # amend 模式下允许空消息（复用上一次提交信息）
    if not amend and (not message or not isinstance(message, str) or len(message) > 200):
        return jsonify({'ok': False, 'error': 'commit message required (max 200 chars)'}), 400
    if isinstance(message, str) and len(message) > 200:
        return jsonify({'ok': False, 'error': 'commit message too long (max 200 chars)'}), 400

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            # amend 且未提供消息时复用上一次提交信息
            if amend and not message:
                message = repo.head.commit.message.strip()
            kwargs = {'amend': True, 'head': repo.head.commit} if amend else {}
            commit = repo.index.commit(message, **kwargs)
            return jsonify({'ok': True, 'hash': commit.hexsha[:7]})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'commit', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/push', methods=['POST'])
async def git_push():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            import subprocess
            # 检查当前分支是否有上游跟踪，没有则自动设置
            branch = repo.active_branch.name
            has_upstream = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', '@{upstream}'],
                cwd=path, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
            )
            cmd = ['git', 'push']
            if has_upstream.returncode != 0:
                cmd = ['git', 'push', '-u', 'origin', branch]
            result = subprocess.run(
                cmd, cwd=path, capture_output=True, text=True, timeout=60,
                encoding='utf-8', errors='replace',
            )
            output = result.stdout
            if result.stderr:
                output += '\n' + result.stderr
            return jsonify({'ok': result.returncode == 0, 'output': output.strip()})
        except subprocess.TimeoutExpired:
            return jsonify({'ok': False, 'error': 'push timed out'})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'push', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/pull', methods=['POST'])
async def git_pull():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    strategy = data.get('strategy', 'merge')  # merge 或 rebase
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if strategy not in ('merge', 'rebase'):
        return jsonify({'ok': False, 'error': 'strategy must be merge or rebase'}), 400

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            import subprocess
            cmd = ['git', 'pull', '--rebase', '--autostash'] if strategy == 'rebase' else ['git', 'pull']
            result = subprocess.run(
                cmd, cwd=path, capture_output=True, text=True, timeout=60,
                encoding='utf-8', errors='replace',
            )
            conflicts = {}
            try:
                unmerged = repo.index.unmerged_blobs()
                if unmerged:
                    conflicts = {k: list(v.keys()) for k, v in unmerged.items()}
            except Exception:
                pass
            return jsonify({
                'ok': result.returncode == 0 or bool(conflicts),
                'output': (result.stdout + '\n' + result.stderr).strip(),
                'hasConflicts': bool(conflicts),
                'conflictFiles': [k for k in conflicts.keys()] if conflicts else [],
            })
        except subprocess.TimeoutExpired:
            return jsonify({'ok': False, 'error': 'pull timed out'})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'pull', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/fetch', methods=['POST'])
async def git_fetch():
    """获取远程更新但不合并，返回本地与远程的差异信息"""
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import subprocess
    with get_git_lock(path):
        try:
            # 先 fetch 远程更新
            fetch_result = subprocess.run(
                ['git', 'fetch'], cwd=path, capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='replace',
            )
            if fetch_result.returncode != 0:
                return jsonify({'ok': False, 'error': (fetch_result.stdout + '\n' + fetch_result.stderr).strip()})

            # 统计 ahead/behind
            count_result = subprocess.run(
                ['git', 'rev-list', '--left-right', '--count', 'HEAD...@{upstream}'],
                cwd=path, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
            )
            ahead, behind = 0, 0
            if count_result.returncode == 0 and count_result.stdout.strip():
                parts = count_result.stdout.strip().split()
                if len(parts) == 2:
                    ahead, behind = int(parts[0]), int(parts[1])

            # 获取远程领先提交列表
            commits = []
            if behind > 0:
                log_result = subprocess.run(
                    ['git', 'log', 'HEAD..@{upstream}', '--oneline', '-20'],
                    cwd=path, capture_output=True, text=True,
                    encoding='utf-8', errors='replace',
                )
                if log_result.returncode == 0 and log_result.stdout.strip():
                    commits = log_result.stdout.strip().split('\n')

            return jsonify({'ok': True, 'ahead': ahead, 'behind': behind, 'commits': commits})
        except subprocess.TimeoutExpired:
            return jsonify({'ok': False, 'error': 'fetch timed out'})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'fetch', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/init', methods=['POST'])
async def git_init():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import git as _git
    with get_git_lock(path):
        def _op():
            _git.Repo.init(path)
            return {'ok': True}
        result, err = _try_git_op('init', _op, path)
        if err:
            return jsonify({'ok': False, 'error': err})
        return jsonify(result)


@git_bp.route('/undo-commit', methods=['POST'])
async def git_undo_commit():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            last_hash = repo.head.commit.hexsha[:7]
            repo.git.reset('--soft', 'HEAD~1')
            return jsonify({'ok': True, 'message': 'reverted commit: ' + last_hash})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'undo-commit', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/reset-file', methods=['POST'])
async def git_reset_file():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    file = data.get('file', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if not file:
        return jsonify({'ok': False, 'error': 'file required'}), 400

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            repo.git.checkout('--', file)
            return jsonify({'ok': True})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'reset-file', 'path': path, 'file': file,
                                    'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/stash', methods=['POST'])
async def git_stash():
    """暂存当前工作区更改"""
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    message = data.get('message', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import subprocess
    with get_git_lock(path):
        try:
            cmd = ['git', 'stash', 'push']
            if message:
                cmd += ['-m', message]
            result = subprocess.run(
                cmd, cwd=path, capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='replace',
            )
            return jsonify({'ok': result.returncode == 0, 'output': result.stdout.strip()})
        except subprocess.TimeoutExpired:
            return jsonify({'ok': False, 'error': 'stash timed out'})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'stash', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/stash-pop', methods=['POST'])
async def git_stash_pop():
    """恢复最近的暂存（从栈中移除）"""
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    index = data.get('index', 0)
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import subprocess
    with get_git_lock(path):
        try:
            cmd = ['git', 'stash', 'pop']
            if index > 0:
                cmd += ['stash@{' + str(index) + '}']
            result = subprocess.run(
                cmd, cwd=path, capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='replace',
            )
            return jsonify({'ok': result.returncode == 0, 'output': (result.stdout + '\n' + result.stderr).strip()})
        except subprocess.TimeoutExpired:
            return jsonify({'ok': False, 'error': 'stash pop timed out'})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'stash-pop', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/stash-apply', methods=['POST'])
async def git_stash_apply():
    """恢复暂存但不从栈中移除"""
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    index = data.get('index', 0)
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import subprocess
    with get_git_lock(path):
        try:
            cmd = ['git', 'stash', 'apply']
            if index > 0:
                cmd += ['stash@{' + str(index) + '}']
            result = subprocess.run(
                cmd, cwd=path, capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='replace',
            )
            return jsonify({'ok': result.returncode == 0, 'output': (result.stdout + '\n' + result.stderr).strip()})
        except subprocess.TimeoutExpired:
            return jsonify({'ok': False, 'error': 'stash apply timed out'})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'stash-apply', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/stash-list', methods=['POST'])
async def git_stash_list():
    """列出所有暂存"""
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import subprocess
    with get_git_lock(path):
        try:
            result = subprocess.run(
                ['git', 'stash', 'list', '--format=%gd %s'],
                cwd=path, capture_output=True, text=True, timeout=10,
                encoding='utf-8', errors='replace',
            )
            stashes = []
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
                    parts = line.split(' ', 1)
                    if len(parts) >= 2:
                        ref = parts[0].strip('{}')
                        idx = int(ref.replace('stash@', '')) if 'stash@' in ref else 0
                        stashes.append({'index': idx, 'message': parts[1]})
                    elif parts:
                        stashes.append({'index': 0, 'message': parts[0]})
            return jsonify({'ok': True, 'stashes': stashes})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'stash-list', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/stash-drop', methods=['POST'])
async def git_stash_drop():
    """删除指定暂存"""
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    index = data.get('index', 0)
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    import subprocess
    with get_git_lock(path):
        try:
            cmd = ['git', 'stash', 'drop', 'stash@{' + str(index) + '}']
            result = subprocess.run(
                cmd, cwd=path, capture_output=True, text=True, timeout=10,
                encoding='utf-8', errors='replace',
            )
            return jsonify({'ok': result.returncode == 0, 'output': result.stderr.strip()})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'stash-drop', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/create-branch', methods=['POST'])
async def git_create_branch():
    """创建新分支，可选切换到新分支"""
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    name = data.get('name', '')
    switch = data.get('switch', False)
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if not name or not isinstance(name, str):
        return jsonify({'ok': False, 'error': 'branch name required'}), 400
    if '/' in name or '..' in name or name.startswith('-'):
        return jsonify({'ok': False, 'error': 'invalid branch name'}), 400

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            if switch:
                repo.git.checkout('-b', name)
            else:
                repo.git.branch(name)
            return jsonify({'ok': True})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'create-branch', 'path': path, 'name': name,
                                    'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/delete-branch', methods=['POST'])
async def git_delete_branch():
    """删除分支，受保护分支需 force=true"""
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    name = data.get('name', '')
    force = data.get('force', False)
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if not name or not isinstance(name, str):
        return jsonify({'ok': False, 'error': 'branch name required'}), 400

    import git as _git
    with get_git_lock(path):
        try:
            repo = _git.Repo(path)
            # 不能删除当前分支
            if repo.active_branch.name == name:
                return jsonify({'ok': False, 'error': 'cannot delete current branch'}), 400
            # 受保护分支校验
            protected = _get_protected_branches()
            if name in protected and not force:
                return jsonify({'ok': False, 'error': 'branch is protected', 'protected': True}), 403
            if force:
                repo.git.branch('-D', name)
            else:
                repo.git.branch('-d', name)
            return jsonify({'ok': True})
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'delete-branch', 'path': path, 'name': name,
                                    'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})
