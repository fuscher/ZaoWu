import asyncio
import functools
import io
import os
import shutil
import traceback
from quart import Blueprint, request, jsonify
from routes.log import append_log
from routes.explorer import is_path_in_projects

git_bp = Blueprint('git', __name__)

_git_locks: dict = {}
_git_locks_lock = asyncio.Lock()

RETRYABLE_OPS = {'check', 'status', 'branches', 'commits', 'init'}

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


async def get_git_lock(path: str) -> asyncio.Lock:
    """获取仓库级异步锁——同一仓库串行，不同仓库并行"""
    async with _git_locks_lock:
        real = os.path.realpath(path)
        if real not in _git_locks:
            _git_locks[real] = asyncio.Lock()
        return _git_locks[real]


def validate_git_path(path):
    if not path:
        return 'missing path'
    try:
        real = os.path.normcase(os.path.realpath(path))
        if not is_path_in_projects(real):
            return 'path is not within registered projects'
        return None
    except Exception as e:
        return str(e)


def validate_file_paths(base_path, files):
    """校验文件路径是否在项目目录内（防 ../ 穿越）"""
    real_base = os.path.normcase(os.path.realpath(base_path))
    for f in files:
        real_file = os.path.normcase(os.path.realpath(os.path.join(base_path, f)))
        if not real_file.startswith(real_base + os.sep) and real_file != real_base:
            return False, f'path traversal: {f}'
    return True, ''


async def _try_git_op(op_name, func, path):
    max_retries = 3 if op_name in RETRYABLE_OPS else 1
    last_error = None
    for attempt in range(max_retries):
        try:
            result = await asyncio.to_thread(func)
            return result, None
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
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


async def _precheck_credential(path):
    """预检 git credential.helper，为空时返回提示（仍继续尝试执行）"""
    try:
        proc = await asyncio.create_subprocess_exec(
            'git', 'config', 'credential.helper',
            cwd=path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0 or not stdout.decode('utf-8', errors='replace').strip():
            return '建议配置 git 凭据助手或 SSH Key，避免操作挂起'
    except Exception:
        pass
    return None


def parse_status(raw):
    changes = []
    if not raw:
        return changes
    for line in raw.strip().split('\n'):
        if not line or len(line) < 3:
            continue
        index_status = line[0]
        worktree_status = line[1]
        file_part = line[3:].strip()

        # 冲突文件（任一列为 U，或 AA/DD）
        if 'U' in (index_status, worktree_status) or (index_status, worktree_status) in (('A', 'A'), ('D', 'D')):
            changes.append({'path': file_part, 'type': 'conflict', 'status': 'conflict'})
            continue

        # 未跟踪文件
        if index_status == '?':
            changes.append({'path': file_part, 'type': 'untracked', 'status': 'untracked'})
            continue

        # 重命名
        if index_status == 'R':
            parts = file_part.split(' -> ')
            old_path = parts[0] if len(parts) > 0 else ''
            new_path = parts[1] if len(parts) > 1 else file_part
            changes.append({
                'path': new_path, 'type': 'renamed', 'status': 'staged', 'oldPath': old_path,
            })
            continue

        # 已暂存
        if index_status in ('M', 'A', 'D'):
            type_map = {'M': 'modified', 'A': 'added', 'D': 'deleted'}
            changes.append({'path': file_part, 'type': type_map.get(index_status, 'modified'), 'status': 'staged'})

        # 未暂存修改
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
            'author': c.author.name if hasattr(c.author, 'name') else str(c.author),
            'authorEmail': c.author.email if hasattr(c.author, 'email') else '',
            'date': c.committed_datetime.isoformat() if c.committed_datetime else '',
            'isLocalTip': c.hexsha[:7] == local_tip,
            'isRemoteTip': remote_tip is not None and c.hexsha[:7] == remote_tip,
        })
    return result


def git_endpoint(rule, methods=None, *, validate_files=False, validate_branch=False):
    """装饰器：统一处理 JSON 解析、路径校验、异步锁、错误日志"""
    def decorator(func):
        @git_bp.route(rule, methods=methods or ['POST'])
        @functools.wraps(func)
        async def wrapper():
            data = await request.get_json(silent=True) or {}
            path = data.get('path', '')
            error = validate_git_path(path)
            if error:
                return jsonify({'ok': False, 'error': error}), 403

            if validate_files:
                files = data.get('files', [])
                if not files or not isinstance(files, list):
                    return jsonify({'ok': False, 'error': 'files list required'}), 400
                ok, err = validate_file_paths(path, files)
                if not ok:
                    return jsonify({'ok': False, 'error': err}), 403

            if validate_branch:
                branch = data.get('branch', '') or data.get('name', '')
                if not branch or not isinstance(branch, str):
                    return jsonify({'ok': False, 'error': 'branch name required'}), 400

            lock = await get_git_lock(path)
            async with lock:
                try:
                    result = await func(path, data)
                    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], int):
                        body, status = result
                        return jsonify(body), status
                    return jsonify(result)
                except Exception as e:
                    append_log({
                        'level': 'error',
                        'type': 'GitOperationError',
                        'message': str(e),
                        'details': {'operation': func.__name__, 'path': path,
                                    'traceback': traceback.format_exc()},
                    })
                    return jsonify({'ok': False, 'error': str(e)})
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@git_bp.route('/check', methods=['POST'])
async def check_git():
    def _op():
        import shutil as _shutil
        return _shutil.which('git') is not None
    result, _ = await _try_git_op('check', _op, 'n/a')
    return jsonify({'available': bool(result)})


@git_bp.route('/status', methods=['POST'])
async def git_status():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    lock = await get_git_lock(path)
    async with lock:
        def _op():
            import git as _git
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
            return jsonify(await asyncio.to_thread(_op))
        except Exception as e:
            import git as _git
            if isinstance(e, _git.InvalidGitRepositoryError):
                return jsonify({'ok': True, 'hasRepo': False, 'changes': [], 'branch': ''})
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'status', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_endpoint('/branches', methods=['POST'])
async def git_branches(path, data):
    def _op():
        import git as _git
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
    result, err = await _try_git_op('branches', _op, path)
    if err:
        return {'ok': False, 'error': err}
    return result


@git_endpoint('/switch-branch', methods=['POST'], validate_branch=True)
async def git_switch_branch(path, data):
    branch = data.get('branch', '')
    if '/' in branch or '..' in branch:
        return {'ok': False, 'error': 'invalid branch name'}, 400

    def _op():
        import git as _git
        repo = _git.Repo(path)
        repo.git.checkout(branch)
    await asyncio.to_thread(_op)
    return {'ok': True}


@git_endpoint('/commits', methods=['POST'])
async def git_commits(path, data):
    limit = data.get('limit', 20)
    offset = data.get('offset', 0)
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        return {'ok': False, 'error': 'limit must be 1-100'}, 400
    if not isinstance(offset, int) or offset < 0:
        return {'ok': False, 'error': 'offset cannot be negative'}, 400

    def _op():
        import git as _git
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
    result, err = await _try_git_op('commits', _op, path)
    if err:
        return {'ok': False, 'error': err}
    return result


@git_endpoint('/stage', methods=['POST'], validate_files=True)
async def git_stage(path, data):
    def _op():
        import git as _git
        repo = _git.Repo(path)
        repo.index.add(data['files'])
    await asyncio.to_thread(_op)
    return {'ok': True}


@git_endpoint('/unstage', methods=['POST'], validate_files=True)
async def git_unstage(path, data):
    def _op():
        import git as _git
        repo = _git.Repo(path)
        repo.git.reset('HEAD', '--', *data['files'])
    await asyncio.to_thread(_op)
    return {'ok': True}


@git_endpoint('/stage-all', methods=['POST'])
async def git_stage_all(path, data):
    def _op():
        import git as _git
        repo = _git.Repo(path)
        repo.git.add('--all')
    await asyncio.to_thread(_op)
    return {'ok': True}


@git_endpoint('/discard', methods=['POST'], validate_files=True)
async def git_discard(path, data):
    files = data['files']
    include_untracked = data.get('includeUntracked', False)

    def _op():
        import git as _git
        repo = _git.Repo(path)
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
        if tracked:
            repo.git.checkout('--', *tracked)
        keep_names = {'.gitkeep', '.gitignore'}
        for f in untracked:
            if os.path.basename(f) in keep_names:
                continue
            full = os.path.join(path, f)
            if os.path.isdir(full):
                shutil.rmtree(full)
            elif os.path.isfile(full):
                os.remove(full)
    await asyncio.to_thread(_op)
    return {'ok': True}


@git_endpoint('/commit', methods=['POST'])
async def git_commit(path, data):
    message = data.get('message', '')
    amend = data.get('amend', False)
    if not amend and (not message or not isinstance(message, str) or len(message) > 200):
        return {'ok': False, 'error': 'commit message required (max 200 chars)'}, 400
    if isinstance(message, str) and len(message) > 200:
        return {'ok': False, 'error': 'commit message too long (max 200 chars)'}, 400

    def _op():
        import git as _git
        repo = _git.Repo(path)
        nonlocal message
        if amend and not message:
            message = repo.head.commit.message.strip()
        kwargs = {'amend': True, 'head': repo.head.commit} if amend else {}
        commit = repo.index.commit(message, **kwargs)
        return {'ok': True, 'hash': commit.hexsha[:7]}
    return await asyncio.to_thread(_op)


@git_bp.route('/push', methods=['POST'])
async def git_push():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403

    cred_hint = await _precheck_credential(path)

    lock = await get_git_lock(path)
    async with lock:
        def _op():
            import git as _git
            import subprocess
            repo = _git.Repo(path)
            branch = repo.active_branch.name
            has_upstream = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', '@{upstream}'],
                cwd=path, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
            )
            cmd = ['git', 'push']
            if has_upstream.returncode != 0:
                cmd = ['git', 'push', '-u', 'origin', branch]
            timeout = 15 if cred_hint else 60
            result = subprocess.run(
                cmd, cwd=path, capture_output=True, text=True, timeout=timeout,
                encoding='utf-8', errors='replace',
            )
            output = result.stdout
            if result.stderr:
                output += '\n' + result.stderr
            if result.returncode == 0 and has_upstream.returncode != 0:
                verify = subprocess.run(
                    ['git', 'rev-parse', '--abbrev-ref', '@{upstream}'],
                    cwd=path, capture_output=True, text=True,
                    encoding='utf-8', errors='replace',
                )
                if verify.returncode != 0:
                    return {'ok': False, 'error': 'push succeeded but upstream not set', 'output': output.strip()}
            return {'ok': result.returncode == 0, 'output': output.strip()}
        try:
            result = await asyncio.to_thread(_op)
            if cred_hint:
                result['credentialHint'] = cred_hint
            return jsonify(result)
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'push', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_bp.route('/pull', methods=['POST'])
async def git_pull():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    strategy = data.get('strategy', 'merge')
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if strategy not in ('merge', 'rebase'):
        return jsonify({'ok': False, 'error': 'strategy must be merge or rebase'}), 400

    cred_hint = await _precheck_credential(path)

    lock = await get_git_lock(path)
    async with lock:
        def _op():
            import git as _git
            import subprocess
            repo = _git.Repo(path)
            protected = _get_protected_branches()
            branch = repo.active_branch.name
            if branch in protected:
                return {'ok': False, 'error': 'cannot pull on protected branch', 'protected': True}, 403
            cmd = ['git', 'pull', '--rebase', '--autostash'] if strategy == 'rebase' else ['git', 'pull', '--autostash']
            timeout = 15 if cred_hint else 60
            result = subprocess.run(
                cmd, cwd=path, capture_output=True, text=True, timeout=timeout,
                encoding='utf-8', errors='replace',
            )
            # 竞态修复：pull 完成后重建 Repo 对象再检测冲突
            repo = _git.Repo(path)
            conflicts = {}
            try:
                unmerged = repo.index.unmerged_blobs()
                if unmerged:
                    conflicts = {k: list(v.keys()) for k, v in unmerged.items()}
            except Exception:
                pass
            return {
                'ok': result.returncode == 0 or bool(conflicts),
                'output': (result.stdout + '\n' + result.stderr).strip(),
                'hasConflicts': bool(conflicts),
                'conflictFiles': [k for k in conflicts.keys()] if conflicts else [],
            }
        try:
            result = await asyncio.to_thread(_op)
            if isinstance(result, tuple):
                body, status = result
                return jsonify(body), status
            if cred_hint:
                result['credentialHint'] = cred_hint
            return jsonify(result)
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'pull', 'path': path, 'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_endpoint('/fetch', methods=['POST'])
async def git_fetch(path, data):
    def _op():
        import subprocess
        fetch_result = subprocess.run(
            ['git', 'fetch'], cwd=path, capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        if fetch_result.returncode != 0:
            return {'ok': False, 'error': (fetch_result.stdout + '\n' + fetch_result.stderr).strip()}
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
        commits = []
        if behind > 0:
            log_result = subprocess.run(
                ['git', 'log', 'HEAD..@{upstream}', '--oneline', '-20'],
                cwd=path, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
            )
            if log_result.returncode == 0 and log_result.stdout.strip():
                commits = log_result.stdout.strip().split('\n')
        return {'ok': True, 'ahead': ahead, 'behind': behind, 'commits': commits}
    return await asyncio.to_thread(_op)


@git_endpoint('/init', methods=['POST'])
async def git_init(path, data):
    def _op():
        import git as _git
        _git.Repo.init(path)
        return {'ok': True}
    result, err = await _try_git_op('init', _op, path)
    if err:
        return {'ok': False, 'error': err}
    return result


@git_endpoint('/undo-commit', methods=['POST'])
async def git_undo_commit(path, data):
    def _op():
        import git as _git
        repo = _git.Repo(path)
        last_hash = repo.head.commit.hexsha[:7]
        repo.git.reset('--soft', 'HEAD~1')
        return {'ok': True, 'message': 'reverted commit: ' + last_hash}
    return await asyncio.to_thread(_op)


@git_endpoint('/reset-file', methods=['POST'], validate_files=True)
async def git_reset_file(path, data):
    file = data['files'][0]

    def _op():
        import git as _git
        repo = _git.Repo(path)
        repo.git.checkout('--', file)
    await asyncio.to_thread(_op)
    return {'ok': True}


@git_endpoint('/stash', methods=['POST'])
async def git_stash(path, data):
    message = data.get('message', '')

    def _op():
        import subprocess
        cmd = ['git', 'stash', 'push']
        if message:
            cmd += ['-m', message]
        result = subprocess.run(
            cmd, cwd=path, capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        return {'ok': result.returncode == 0, 'output': result.stdout.strip()}
    return await asyncio.to_thread(_op)


@git_endpoint('/stash-pop', methods=['POST'])
async def git_stash_pop(path, data):
    index = data.get('index', 0)

    def _op():
        import subprocess
        cmd = ['git', 'stash', 'pop', '--index']
        if index > 0:
            cmd += ['stash@{' + str(index) + '}']
        result = subprocess.run(
            cmd, cwd=path, capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        has_conflicts = result.returncode != 0 and 'CONFLICT' in (result.stderr + result.stdout)
        return {
            'ok': result.returncode == 0 or has_conflicts,
            'hasConflicts': has_conflicts,
            'output': (result.stdout + '\n' + result.stderr).strip(),
        }
    return await asyncio.to_thread(_op)


@git_endpoint('/stash-apply', methods=['POST'])
async def git_stash_apply(path, data):
    index = data.get('index', 0)

    def _op():
        import subprocess
        cmd = ['git', 'stash', 'apply', '--index']
        if index > 0:
            cmd += ['stash@{' + str(index) + '}']
        result = subprocess.run(
            cmd, cwd=path, capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        has_conflicts = result.returncode != 0 and 'CONFLICT' in (result.stderr + result.stdout)
        return {
            'ok': result.returncode == 0 or has_conflicts,
            'hasConflicts': has_conflicts,
            'output': (result.stdout + '\n' + result.stderr).strip(),
        }
    return await asyncio.to_thread(_op)


@git_endpoint('/stash-list', methods=['POST'])
async def git_stash_list(path, data):
    def _op():
        import subprocess
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
        return {'ok': True, 'stashes': stashes}
    return await asyncio.to_thread(_op)


@git_endpoint('/stash-drop', methods=['POST'])
async def git_stash_drop(path, data):
    index = data.get('index', 0)

    def _op():
        import subprocess
        cmd = ['git', 'stash', 'drop', 'stash@{' + str(index) + '}']
        result = subprocess.run(
            cmd, cwd=path, capture_output=True, text=True, timeout=10,
            encoding='utf-8', errors='replace',
        )
        return {'ok': result.returncode == 0, 'output': result.stderr.strip()}
    return await asyncio.to_thread(_op)


@git_endpoint('/create-branch', methods=['POST'], validate_branch=True)
async def git_create_branch(path, data):
    name = data.get('name', '')
    switch = data.get('switch', False)
    if '/' in name or '..' in name or name.startswith('-'):
        return {'ok': False, 'error': 'invalid branch name'}, 400

    def _op():
        import git as _git
        repo = _git.Repo(path)
        if switch:
            repo.git.checkout('--no-track', '-b', name)
        else:
            repo.git.branch('--no-track', name)
    await asyncio.to_thread(_op)
    return {'ok': True}


@git_bp.route('/delete-branch', methods=['POST'])
async def git_delete_branch():
    data = await request.get_json(silent=True) or {}
    path = data.get('path', '')
    name = data.get('name', '')
    force = data.get('force', False)
    error = validate_git_path(path)
    if error:
        return jsonify({'ok': False, 'error': error}), 403
    if not name or not isinstance(name, str):
        return jsonify({'ok': False, 'error': 'branch name required'}), 400

    lock = await get_git_lock(path)
    async with lock:
        def _op():
            import git as _git
            repo = _git.Repo(path)
            if repo.active_branch.name == name:
                return {'ok': False, 'error': 'cannot delete current branch'}, 400
            protected = _get_protected_branches()
            if name in protected and not force:
                return {'ok': False, 'error': 'branch is protected', 'protected': True}, 403
            if force:
                repo.git.branch('-D', name)
            else:
                repo.git.branch('-d', name)
            return {'ok': True}
        try:
            result = await asyncio.to_thread(_op)
            if isinstance(result, tuple):
                body, status = result
                return jsonify(body), status
            return jsonify(result)
        except Exception as e:
            append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                        'details': {'operation': 'delete-branch', 'path': path, 'name': name,
                                    'traceback': traceback.format_exc()}})
            return jsonify({'ok': False, 'error': str(e)})


@git_endpoint('/resolve-accept-ours', methods=['POST'], validate_files=True)
async def git_resolve_accept_ours(path, data):
    def _op():
        import subprocess
        result = subprocess.run(
            ['git', 'checkout', '--ours', '--'] + data['files'],
            cwd=path, capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        if result.returncode != 0:
            return {'ok': False, 'error': result.stderr.strip()}
        result2 = subprocess.run(
            ['git', 'add', '--'] + data['files'],
            cwd=path, capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        return {'ok': result2.returncode == 0}
    return await asyncio.to_thread(_op)


@git_endpoint('/resolve-accept-theirs', methods=['POST'], validate_files=True)
async def git_resolve_accept_theirs(path, data):
    def _op():
        import subprocess
        result = subprocess.run(
            ['git', 'checkout', '--theirs', '--'] + data['files'],
            cwd=path, capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        if result.returncode != 0:
            return {'ok': False, 'error': result.stderr.strip()}
        result2 = subprocess.run(
            ['git', 'add', '--'] + data['files'],
            cwd=path, capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        return {'ok': result2.returncode == 0}
    return await asyncio.to_thread(_op)


@git_endpoint('/diff', methods=['POST'])
async def git_diff(path, data):
    file = data.get('file', '')
    staged = data.get('staged', False)

    def _op():
        import subprocess
        cmd = ['git', 'diff']
        if staged:
            cmd.append('--staged')
        if file:
            cmd += ['--', file]
        result = subprocess.run(
            cmd, cwd=path, capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        output = result.stdout
        if len(output) > 100_000:
            output = output[:100_000] + '\n... (truncated)'
        return {'ok': True, 'diff': output}
    return await asyncio.to_thread(_op)


@git_endpoint('/remote-list', methods=['POST'])
async def git_remote_list(path, data):
    def _op():
        import subprocess
        result = subprocess.run(
            ['git', 'remote', '-v'],
            cwd=path, capture_output=True, text=True, timeout=10,
            encoding='utf-8', errors='replace',
        )
        remotes = []
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 2:
                    remotes.append({'name': parts[0], 'url': parts[1], 'type': parts[2] if len(parts) > 2 else ''})
        return {'ok': True, 'remotes': remotes}
    return await asyncio.to_thread(_op)


@git_endpoint('/remote-add', methods=['POST'])
async def git_remote_add(path, data):
    name = data.get('name', '')
    url = data.get('url', '')
    if not name or not url:
        return {'ok': False, 'error': 'name and url required'}, 400

    def _op():
        import subprocess
        result = subprocess.run(
            ['git', 'remote', 'add', name, url],
            cwd=path, capture_output=True, text=True, timeout=10,
            encoding='utf-8', errors='replace',
        )
        return {'ok': result.returncode == 0, 'error': result.stderr.strip() if result.returncode != 0 else ''}
    return await asyncio.to_thread(_op)


@git_endpoint('/remote-remove', methods=['POST'])
async def git_remote_remove(path, data):
    name = data.get('name', '')
    if not name:
        return {'ok': False, 'error': 'remote name required'}, 400

    def _op():
        import subprocess
        result = subprocess.run(
            ['git', 'remote', 'remove', name],
            cwd=path, capture_output=True, text=True, timeout=10,
            encoding='utf-8', errors='replace',
        )
        return {'ok': result.returncode == 0}
    return await asyncio.to_thread(_op)


@git_endpoint('/tags', methods=['POST'])
async def git_tags(path, data):
    def _op():
        import subprocess
        result = subprocess.run(
            ['git', 'tag', '--sort=-creatordate'],
            cwd=path, capture_output=True, text=True, timeout=10,
            encoding='utf-8', errors='replace',
        )
        tags = [t.strip() for t in result.stdout.strip().split('\n') if t.strip()] if result.returncode == 0 else []
        return {'ok': True, 'tags': tags}
    return await asyncio.to_thread(_op)


@git_endpoint('/create-tag', methods=['POST'])
async def git_create_tag(path, data):
    name = data.get('name', '')
    message = data.get('message', '')
    if not name:
        return {'ok': False, 'error': 'tag name required'}, 400

    def _op():
        import subprocess
        cmd = ['git', 'tag']
        if message:
            cmd += ['-a', name, '-m', message]
        else:
            cmd.append(name)
        result = subprocess.run(
            cmd, cwd=path, capture_output=True, text=True, timeout=10,
            encoding='utf-8', errors='replace',
        )
        return {'ok': result.returncode == 0, 'error': result.stderr.strip() if result.returncode != 0 else ''}
    return await asyncio.to_thread(_op)


@git_bp.route('/clone', methods=['POST'])
async def git_clone():
    data = await request.get_json(silent=True) or {}
    url = data.get('url', '')
    dest = data.get('dest', '')
    if not url or not isinstance(url, str):
        return jsonify({'ok': False, 'error': 'url required'}), 400
    if not dest or not isinstance(dest, str):
        return jsonify({'ok': False, 'error': 'dest required'}), 400

    parent = os.path.dirname(os.path.realpath(dest))
    parent_error = validate_git_path(parent)
    if parent_error:
        return jsonify({'ok': False, 'error': parent_error}), 403

    def _op():
        import subprocess
        if os.path.exists(dest):
            return {'ok': False, 'error': 'destination already exists'}
        result = subprocess.run(
            ['git', 'clone', url, dest],
            capture_output=True, text=True, timeout=120,
            encoding='utf-8', errors='replace',
        )
        if result.returncode != 0:
            return {'ok': False, 'error': (result.stdout + '\n' + result.stderr).strip()}
        return {'ok': True, 'path': os.path.realpath(dest)}
    try:
        return jsonify(await asyncio.to_thread(_op))
    except Exception as e:
        append_log({'level': 'error', 'type': 'GitOperationError', 'message': str(e),
                    'details': {'operation': 'clone', 'url': url, 'dest': dest,
                                'traceback': traceback.format_exc()}})
        return jsonify({'ok': False, 'error': str(e)})
