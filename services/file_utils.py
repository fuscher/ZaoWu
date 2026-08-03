"""文件操作纯函数 — 供智能体工具调用使用，不依赖 Quart request 上下文。"""
import os
import difflib
import asyncio

MAX_FILE_SIZE = 1024 * 1024  # 1MB
MAX_DIFF_LENGTH = 6_000  # unified diff 输出上限（预留余量给 _format_result JSON 打包）
MAX_LINE_LENGTH = 2000  # read_file 单行最大字符数，超出截断（防止 minified 文件单行撑爆 token）
DEFAULT_READ_LIMIT = 2000  # read_file 默认读取行数上限

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


def read_file_content(path: str, offset: int = 1, limit: int = DEFAULT_READ_LIMIT) -> dict:
    """读取文件内容（纯函数，不依赖 request）

    返回带行号前缀的内容（``{行号}: {内容}`` 格式），便于 LLM 用 file:line 精确引用。
    支持 offset/limit 分页读取大文件，避免一次吞掉数万 token。单行超过
    MAX_LINE_LENGTH 字符自动截断（minified JS / 压缩 JSON 等场景）。

    二进制文件前置拒绝（与 write_file/edit_file 行为一致，避免读到乱码）。

    Args:
        path: 文件绝对路径
        offset: 起始行号（1-indexed，默认 1）
        limit: 读取的最大行数（默认 2000）
    """
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        return {'ok': False, 'error': 'not a file'}
    if is_binary_file(real):
        return {'ok': False, 'error': 'cannot read binary file'}
    try:
        size = os.path.getsize(real)
        if size > MAX_FILE_SIZE:
            return {'ok': False, 'error': f'file too large ({size} bytes)'}
        with open(real, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        total_lines = len(all_lines)
        # offset 1-indexed，clamp 到 [1, total_lines]；超出范围返回空内容
        offset = max(1, offset)
        start = offset - 1
        end = start + max(1, limit)
        selected = all_lines[start:end]
        # 加行号前缀 + 超长行截断（去掉行尾后截断，再以 \n 重组）
        numbered = []
        for idx, raw_line in enumerate(selected, start=offset):
            content = raw_line.rstrip('\n').rstrip('\r')
            if len(content) > MAX_LINE_LENGTH:
                content = content[:MAX_LINE_LENGTH] + '... (line truncated)'
            numbered.append(f'{idx}: {content}')
        content_str = '\n'.join(numbered)
        # 分页提示：当返回的不是全文时，附注总行数与下一页 offset，
        # 让 LLM 知道是否需要继续读取（_format_result 仅透传 content，故提示须内嵌）
        shown_end = offset + len(selected) - 1
        if selected and shown_end < total_lines:
            content_str += (
                f'\n\n(showing lines {offset}-{shown_end} of {total_lines}; '
                f'use offset={shown_end + 1} to read more)'
            )
        elif not selected and total_lines > 0:
            content_str = f'(file has {total_lines} lines; offset {offset} is beyond end of file)'
        return {
            'ok': True,
            'content': content_str,
            'size': size,
            'path': real,
            'totalLines': total_lines,
            'offset': offset,
            'limit': limit,
        }
    except UnicodeDecodeError:
        return {'ok': False, 'error': 'binary file cannot be read as text'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _detect_file_style(real_path: str) -> tuple[bool, str]:
    """检测文件的 BOM 与行尾风格。文件不存在返回 (False, '\\n')。

    读 bytes 而非 text——text 模式会自动转换 \\r\\n → \\n，无法准确统计原行尾。
    """
    if not os.path.isfile(real_path):
        return False, '\n'
    try:
        with open(real_path, 'rb') as f:
            data = f.read(MAX_FILE_SIZE + 1)
    except OSError:
        return False, '\n'
    has_bom = data.startswith(b'\xef\xbb\xbf')
    crlf = data.count(b'\r\n')
    lone_lf = data.count(b'\n') - crlf
    newline = '\r\n' if crlf > lone_lf else '\n'
    return has_bom, newline


def _write_with_style(real: str, content: str, has_bom: bool, newline: str) -> int:
    """按指定 BOM/行尾风格写入文件，返回写入字节数。

    newline='' 阻止 Python 把 \\n 转为系统默认行尾（Windows 下是 \\r\\n），
    让我们完全控制行尾。utf-8-sig 写入时自动前置 BOM。
    """
    # 先消除混合行尾，再按目标行尾转换
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    if newline == '\r\n':
        content = content.replace('\n', '\r\n')
    encoding = 'utf-8-sig' if has_bom else 'utf-8'
    with open(real, 'w', encoding=encoding, newline='') as f:
        f.write(content)
    return len(content.encode('utf-8'))


def _make_unified_diff(path: str, old_content: str, new_content: str) -> str:
    """生成 unified diff 字符串，超长截断。"""
    # 规范化行尾，避免 \\r\\n 在 diff 输出中产生噪音
    old_norm = old_content.replace('\r\n', '\n').replace('\r', '\n')
    new_norm = new_content.replace('\r\n', '\n').replace('\r', '\n')
    basename = os.path.basename(path)
    diff = ''.join(difflib.unified_diff(
        old_norm.splitlines(keepends=True),
        new_norm.splitlines(keepends=True),
        fromfile=f'a/{basename}',
        tofile=f'b/{basename}',
    ))
    if len(diff) > MAX_DIFF_LENGTH:
        diff = diff[:MAX_DIFF_LENGTH] + '\n... (diff truncated)'
    return diff


def _fuzzy_find_line_ranges(content: str, old_string: str) -> list[tuple[int, int]]:
    """行 strip 模糊匹配：逐行 strip 后比较，返回非重叠匹配区间（起止行索引，end exclusive）。

    用 split('\\n') 而非 splitlines()：splitlines 会消费多种 Unicode 行尾，
    不符合文件实际语义；且 split 保留末尾空字符串元素，便于重组。
    """
    content_norm = content.replace('\r\n', '\n').replace('\r', '\n')
    old_norm = old_string.replace('\r\n', '\n').replace('\r', '\n')

    content_lines = content_norm.split('\n')
    old_lines = old_norm.split('\n')

    # 若 old_string 末尾是换行，split 后会多一个末尾空串，去掉它以免永远匹配不上
    if old_norm.endswith('\n') and old_lines and old_lines[-1] == '':
        old_lines = old_lines[:-1]

    old_stripped = [line.strip() for line in old_lines]
    content_stripped = [line.strip() for line in content_lines]

    m = len(old_stripped)
    if m == 0:
        return []
    n = len(content_stripped)

    raw_matches: list[tuple[int, int]] = []
    for i in range(n - m + 1):
        if all(content_stripped[i + j] == old_stripped[j] for j in range(m)):
            raw_matches.append((i, i + m))

    # 贪心去重：按 start 升序，跳过与前一个重叠的区间
    raw_matches.sort(key=lambda r: r[0])
    non_overlapping: list[tuple[int, int]] = []
    last_end = -1
    for start, end in raw_matches:
        if start >= last_end:
            non_overlapping.append((start, end))
            last_end = end
    return non_overlapping


def _apply_line_replacements(content: str, target_ranges: list[tuple[int, int]],
                             new_string: str) -> str:
    """用 new_string 整段替换命中的行段。按 start 降序替换避免索引偏移。"""
    content_norm = content.replace('\r\n', '\n').replace('\r', '\n')
    lines = content_norm.split('\n')
    new_segment = new_string.replace('\r\n', '\n').replace('\r', '\n').split('\n')

    for start, end in sorted(target_ranges, key=lambda r: -r[0]):
        lines = lines[:start] + new_segment + lines[end:]
    return '\n'.join(lines)


def write_file_content(path: str, content: str) -> dict:
    """写入文件内容（纯函数，不依赖 request）

    允许创建新文件（仅限项目内路径，路径白名单由 ToolExecutor 验证），
    含新建子目录（自动 makedirs）。保留原文件 BOM 与行尾风格；新文件用
    UTF-8 无 BOM + LF。写入后触发 zaowu_on_file_saved 插件 hook。
    """
    real = os.path.realpath(path)
    if is_binary_file(real):
        return {'ok': False, 'error': 'cannot write to binary file path (use a text extension)'}
    parent = os.path.dirname(real)
    existed_before = os.path.isfile(real)
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        has_bom, newline = _detect_file_style(real)
        old_content = ''
        if existed_before:
            try:
                with open(real, 'r', encoding='utf-8-sig' if has_bom else 'utf-8') as f:
                    old_content = f.read()
            except UnicodeDecodeError:
                old_content = ''
        bytes_written = _write_with_style(real, content, has_bom, newline)
        diff = _make_unified_diff(real, old_content, content)
        _fire_file_hook('zaowu_on_file_saved', real)
        return {
            'ok': True,
            'path': real,
            'diff': diff,
            'created': not existed_before,
            'bytes_written': bytes_written,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def edit_file_content(path: str, old_string: str, new_string: str,
                      replace_all: bool = False) -> dict:
    """精确编辑文件的一段内容（纯函数，不依赖 request）。

    用 old_string 定位替换为 new_string。匹配策略两层：
    1. 精确字符串匹配（content.count / content.replace）
    2. 精确失败时：行 strip 模糊匹配（容忍缩进差异）

    保留原文件 BOM 与行尾风格。写入后触发 zaowu_on_file_saved 插件 hook。
    """
    real = os.path.realpath(path)
    if not os.path.exists(real):
        return {'ok': False, 'error': 'file does not exist'}
    if os.path.isdir(real):
        return {'ok': False, 'error': 'path is a directory, not a file'}
    if is_binary_file(real):
        return {'ok': False, 'error': 'cannot edit binary file'}
    if not old_string:
        return {'ok': False, 'error': 'old_string is empty'}
    if old_string == new_string:
        return {'ok': False, 'error': 'old_string and new_string are identical (no change)'}

    has_bom, newline = _detect_file_style(real)
    try:
        with open(real, 'r', encoding='utf-8-sig' if has_bom else 'utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        return {'ok': False, 'error': 'binary file cannot be edited as text'}

    # 第一层：精确字符串匹配
    exact_count = content.count(old_string)
    if exact_count > 0:
        if exact_count > 1 and not replace_all:
            return {'ok': False,
                    'error': f'old_string matches {exact_count} locations; '
                             f'provide more context or set replace_all=true'}
        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = exact_count
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1
    else:
        # 第二层：行 strip 模糊匹配
        match_ranges = _fuzzy_find_line_ranges(content, old_string)
        if not match_ranges:
            return {'ok': False,
                    'error': 'old_string not found (exact and fuzzy match both failed)'}
        if len(match_ranges) > 1 and not replace_all:
            return {'ok': False,
                    'error': f'fuzzy match found {len(match_ranges)} locations; '
                             f'provide more context or set replace_all=true'}
        target_ranges = match_ranges if replace_all else [match_ranges[0]]
        new_content = _apply_line_replacements(content, target_ranges, new_string)
        replacements = len(target_ranges)

    try:
        bytes_written = _write_with_style(real, new_content, has_bom, newline)
        diff = _make_unified_diff(real, content, new_content)
        _fire_file_hook('zaowu_on_file_saved', real)
        return {
            'ok': True,
            'path': real,
            'diff': diff,
            'replacements': replacements,
            'bytes_written': bytes_written,
        }
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
