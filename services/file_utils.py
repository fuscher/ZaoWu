"""文件操作纯函数 — 供智能体工具调用使用，不依赖 Quart request 上下文。"""
import os
import asyncio

MAX_FILE_SIZE = 1024 * 1024  # 1MB

# ── 已知二进制文件扩展名（文件浏览 / 搜索时自动跳过）─────────────────
# 此常量是权威来源；新增或删除扩展名只需修改此处。

BINARY_EXTENSIONS: frozenset[str] = frozenset({
    '.exe', '.dll', '.so', '.dylib', '.bin', '.dat', '.pdb', '.obj', '.o', '.a', '.lib',
    '.class', '.pyc', '.pyo', '.jar', '.war', '.ear',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svg', '.tiff', '.psd', '.ai',
    '.mp3', '.wav', '.ogg', '.flac', '.aac', '.wma', '.m4a',
    '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.mpg', '.mpeg',
    '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.zst',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.ttf', '.otf', '.woff', '.woff2', '.eot',
    '.iso', '.img', '.vhd', '.vmdk', '.ova',
})


def is_binary_file(filepath: str) -> bool:
    """检测文件是否为已知二进制类型（扩展名匹配）。"""
    _, ext = os.path.splitext(filepath)
    return ext.lower() in BINARY_EXTENSIONS


def read_file_content(path: str) -> dict:
    """读取文件内容（纯函数，不依赖 request）"""
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        return {'ok': False, 'error': 'not a file'}
    try:
        size = os.path.getsize(real)
        if size > MAX_FILE_SIZE:
            return {'ok': False, 'error': f'file too large ({size} bytes)'}
        with open(real, 'r', encoding='utf-8') as f:
            content = f.read()
        return {'ok': True, 'content': content, 'size': size, 'path': real}
    except UnicodeDecodeError:
        return {'ok': False, 'error': 'binary file cannot be read as text'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def write_file_content(path: str, content: str) -> dict:
    """写入文件内容（纯函数，不依赖 request）

    允许创建新文件（仅限项目内路径，路径白名单由 ToolExecutor 验证）。
    写入后触发 zaowu_on_file_saved 插件 hook。
    """
    real = os.path.realpath(path)
    parent = os.path.dirname(real)
    if not os.path.isdir(parent):
        return {'ok': False, 'error': 'parent directory does not exist'}
    try:
        os.makedirs(parent, exist_ok=True)
        with open(real, 'w', encoding='utf-8') as f:
            f.write(content)
        _fire_file_hook('zaowu_on_file_saved', real)
        return {'ok': True, 'path': real}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _fire_file_hook(hook_name: str, *paths: str) -> None:
    """触发文件操作插件 hook

    使用 asyncio.run_coroutine_threadsafe 在子线程中触发异步 hook。
    write_file_content 通过 asyncio.to_thread 在子线程执行，子线程无事件循环，
    必须使用主事件循环引用。
    """
    try:
        from plugin_system import get_plugin_manager
        pm = get_plugin_manager()
        if pm is None:
            return
        # 获取主事件循环引用（server_quart.py 在启动时设置）
        main_loop = getattr(asyncio, '_zaowu_main_loop', None)
        if main_loop is None:
            return

        async def _run():
            try:
                await pm.fire_hook(hook_name, *paths)
            except Exception:
                pass

        main_loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(_run(), loop=main_loop)
        )
    except Exception:
        pass


def list_directory(path: str, depth: int = 1, max_depth: int = 3) -> dict:
    """列出目录内容（纯函数）"""
    real = os.path.realpath(path)
    if not os.path.isdir(real):
        return {'ok': False, 'error': 'not a directory'}

    depth = min(depth, max_depth)

    def _build_tree(current_path: str, current_depth: int) -> list:
        if current_depth > depth:
            return []
        items = []
        try:
            entries = sorted(os.scandir(current_path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return [{'name': '<permission denied>', 'type': 'error'}]

        for entry in entries:
            if entry.name.startswith('.') and entry.name not in ('.gitignore', '.env.example'):
                continue
            item = {
                'name': entry.name,
                'type': 'directory' if entry.is_dir() else 'file',
            }
            if entry.is_dir() and current_depth < depth:
                item['children'] = _build_tree(entry.path, current_depth + 1)
            elif not entry.is_dir():
                try:
                    item['size'] = entry.stat().st_size
                except OSError:
                    item['size'] = 0
            items.append(item)
        return items

    tree = _build_tree(real, 1)
    return {'ok': True, 'tree': tree, 'path': real}
