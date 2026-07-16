"""Git 操作纯函数 — 供智能体工具调用使用，不依赖 Quart request 上下文。"""
import os
import subprocess


def get_git_status(project_path: str) -> dict:
    """获取 Git 状态（纯函数）"""
    real = os.path.realpath(project_path)
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=real,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {'ok': False, 'error': result.stderr.strip()}

        files = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            status_code = line[:2].strip()
            filename = line[3:].strip()
            status_map = {
                'M': 'modified',
                'A': 'added',
                'D': 'deleted',
                'R': 'renamed',
                'C': 'copied',
                'U': 'unmerged',
                '??': 'untracked',
                'M ': 'modified (staged)',
                'A ': 'added (staged)',
                'D ': 'deleted (staged)',
            }
            status = status_map.get(status_code, status_code)
            files.append({'status': status, 'file': filename})

        return {'ok': True, 'files': files, 'total': len(files), 'path': real}
    except FileNotFoundError:
        return {'ok': False, 'error': 'git not found'}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'git status timed out'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def get_git_diff(project_path: str, staged: bool = False) -> dict:
    """获取 Git 差异（纯函数）"""
    real = os.path.realpath(project_path)
    try:
        cmd = ['git', 'diff']
        if staged:
            cmd.append('--staged')
        result = subprocess.run(
            cmd,
            cwd=real,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {'ok': False, 'error': result.stderr.strip()}

        output = result.stdout
        if len(output) > 50_000:
            output = output[:50_000] + '\n... (truncated)'

        return {'ok': True, 'diff': output, 'path': real}
    except FileNotFoundError:
        return {'ok': False, 'error': 'git not found'}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'git diff timed out'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def get_recent_commits(project_path: str, count: int = 5) -> dict:
    """获取最近提交记录（纯函数）"""
    real = os.path.realpath(project_path)
    try:
        result = subprocess.run(
            ['git', 'log', f'-{count}', '--oneline', '--decorate'],
            cwd=real,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {'ok': False, 'error': result.stderr.strip()}

        commits = [line.strip() for line in result.stdout.strip().split('\n') if line]
        return {'ok': True, 'commits': commits, 'count': len(commits)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
