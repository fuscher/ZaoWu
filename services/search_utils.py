"""代码搜索纯函数 — 供智能体工具调用使用，不依赖 Quart request 上下文。"""
import os
import json


def search_project(query: str, project_path: str = None) -> dict:
    """在项目中搜索代码（纯函数）"""
    from routes.explorer import read_projects

    settings = _read_settings()
    max_file_size_kb = settings.get('searchMaxFileSizeKB', 1024)
    result_limit = settings.get('searchResultLimit', 500)

    query_lower = query.lower()
    projects = read_projects()
    active_projects = [p for p in projects if not _is_archived(p.get('path', ''))]

    # 补充虚拟协作项目路径
    try:
        from community_ws import _room_project_paths
        for vid, vpath in _room_project_paths.items():
            if os.path.isdir(vpath):
                active_projects.append({'id': vid, 'path': vpath})
    except ImportError:
        pass

    # 如果指定了项目路径，仅搜该项目
    if project_path:
        active_projects = [p for p in active_projects
                          if os.path.realpath(p['path']) == os.path.realpath(project_path)]

    results = []
    total_files = 0
    total_matches = 0

    for project in active_projects:
        p_path = project.get('path', '')
        if not os.path.isdir(p_path):
            continue
        for root, dirs, files in os.walk(p_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')
                       and d not in ('node_modules', '__pycache__', '.git', 'dist', 'build')]
            for filename in files:
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
                        'matches': file_matches[:50],
                    })
                    if total_matches >= result_limit:
                        break
            if total_matches >= result_limit:
                break

    return {
        'ok': True,
        'results': results,
        'totalFiles': total_files,
        'totalMatches': total_matches,
        'query': query,
    }


def _read_settings() -> dict:
    """读取 settings.json"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    settings_file = os.path.join(base_dir, 'settings.json')
    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _is_archived(project_path: str) -> bool:
    """检测项目是否已归档"""
    zaowu_path = os.path.join(project_path, '.zaowu')
    if not os.path.exists(zaowu_path):
        return False
    try:
        with open(zaowu_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('archived', False)
    except (json.JSONDecodeError, IOError):
        return False


BINARY_EXTS = {
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


def _is_binary(filepath: str) -> bool:
    """检测文件是否为二进制（扩展名匹配）"""
    _, ext = os.path.splitext(filepath)
    return ext.lower() in BINARY_EXTS


def _search_in_file(filepath: str, query_lower: str, max_file_size_kb: int = 1024) -> list:
    """在单个文件中搜索关键词"""
    matches = []
    try:
        size_kb = os.path.getsize(filepath) / 1024
        if size_kb > max_file_size_kb:
            return matches
    except OSError:
        return matches

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for i, line in enumerate(f, 1):
                lower_line = line.lower()
                start = 0
                while True:
                    idx = lower_line.find(query_lower, start)
                    if idx == -1:
                        break
                    matches.append({
                        'type': 'content',
                        'line': i,
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
