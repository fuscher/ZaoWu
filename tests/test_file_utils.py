"""file_utils 写入工具修复与 edit_file 功能单元测试。

用 tmp_path fixture 创建临时文件，不依赖 real_executor / 项目路径白名单
（白名单校验属 ToolExecutor 职责，此处只测纯函数行为）。
"""
from services.file_utils import (
    write_file_content, edit_file_content, read_file_content,
    MAX_DIFF_LENGTH, MAX_LINE_LENGTH,
)


# ── read_file 增强测试 ───────────────────────────────────────

def test_read_file_returns_line_number_prefix(tmp_path):
    """read_file 返回 `{行号}: {内容}` 前缀，便于 LLM 用 file:line 引用。"""
    target = tmp_path / 'r.py'
    target.write_text('foo\nbar\nbaz\n', encoding='utf-8')
    result = read_file_content(str(target))
    assert result['ok'] is True
    assert result['content'] == '1: foo\n2: bar\n3: baz'
    assert result['totalLines'] == 3


def test_read_file_offset_pagination(tmp_path):
    """offset 从指定行号开始读（1-indexed）。"""
    target = tmp_path / 'off.py'
    target.write_text('l1\nl2\nl3\nl4\nl5\n', encoding='utf-8')
    result = read_file_content(str(target), offset=3)
    assert result['ok'] is True
    assert result['content'] == '3: l3\n4: l4\n5: l5'
    assert result['offset'] == 3


def test_read_file_limit(tmp_path):
    """limit 限制返回行数，超出部分附分页提示让 LLM 知道还有更多内容。"""
    target = tmp_path / 'lim.py'
    target.write_text('l1\nl2\nl3\nl4\nl5\n', encoding='utf-8')
    result = read_file_content(str(target), offset=1, limit=2)
    assert result['ok'] is True
    assert result['content'].startswith('1: l1\n2: l2')
    assert 'showing lines 1-2 of 5' in result['content']
    assert 'offset=3' in result['content']
    assert result['limit'] == 2


def test_read_file_offset_beyond_end_returns_hint(tmp_path):
    """offset 超出文件总行数时返回提示（而非空内容），告知文件实际行数。"""
    target = tmp_path / 'be.py'
    target.write_text('only\n', encoding='utf-8')
    result = read_file_content(str(target), offset=99)
    assert result['ok'] is True
    assert 'beyond end of file' in result['content']
    assert result['totalLines'] == 1


def test_read_file_rejects_binary(tmp_path):
    """二进制文件前置拒绝（与 write_file/edit_file 行为一致）。"""
    target = tmp_path / 'x.png'
    target.write_bytes(b'\x89PNG\r\n')
    result = read_file_content(str(target))
    assert result['ok'] is False
    assert 'binary' in result['error']


def test_read_file_truncates_long_line(tmp_path):
    """单行超过 MAX_LINE_LENGTH 字符自动截断。"""
    target = tmp_path / 'long.py'
    target.write_text('x' * (MAX_LINE_LENGTH + 100) + '\n', encoding='utf-8')
    result = read_file_content(str(target))
    assert result['ok'] is True
    line = result['content']
    assert 'line truncated' in line
    # 截断后行长度受控（行号前缀 + 截断内容 + 标记）
    assert len(line) < MAX_LINE_LENGTH + 100


def test_read_file_nonexistent_errors(tmp_path):
    result = read_file_content(str(tmp_path / 'nope.py'))
    assert result['ok'] is False
    assert 'not a file' in result['error']


def test_read_file_no_trailing_newline(tmp_path):
    """末行无换行符时行号前缀仍正确，不额外追加空行。"""
    target = tmp_path / 'noeol.py'
    target.write_text('a\nb', encoding='utf-8')
    result = read_file_content(str(target))
    assert result['ok'] is True
    assert result['content'] == '1: a\n2: b'
    assert result['totalLines'] == 2


# ── write_file 修复测试 ──────────────────────────────────────

def test_write_file_creates_in_new_subdirectory(tmp_path):
    """回归核心 bug：父目录不存在时应自动 makedirs 创建，而非报错。"""
    target = tmp_path / 'a' / 'b' / 'c.py'
    result = write_file_content(str(target), 'print(1)')
    assert result['ok'] is True
    assert target.is_file()
    assert target.read_text(encoding='utf-8') == 'print(1)'


def test_write_file_rejects_binary_extension(tmp_path):
    target = tmp_path / 'x.png'
    result = write_file_content(str(target), 'not really png')
    assert result['ok'] is False
    assert 'binary' in result['error']


def test_write_file_preserves_utf8_bom(tmp_path):
    target = tmp_path / 'bom.py'
    with open(target, 'w', encoding='utf-8-sig') as f:
        f.write('old content')
    result = write_file_content(str(target), 'new content')
    assert result['ok'] is True
    assert target.read_bytes().startswith(b'\xef\xbb\xbf')


def test_write_file_preserves_crlf(tmp_path):
    target = tmp_path / 'crlf.py'
    target.write_bytes(b'line1\r\nline2\r\n')
    result = write_file_content(str(target), 'line1\nline2\n')
    assert result['ok'] is True
    data = target.read_bytes()
    assert b'\r\n' in data


def test_write_file_new_file_uses_lf_no_bom(tmp_path):
    target = tmp_path / 'new.py'
    result = write_file_content(str(target), 'line1\nline2\n')
    assert result['ok'] is True
    data = target.read_bytes()
    assert not data.startswith(b'\xef\xbb\xbf')
    assert b'\r\n' not in data


def test_write_file_returns_diff(tmp_path):
    target = tmp_path / 'd.py'
    target.write_text('a\nb\nc\n', encoding='utf-8')
    result = write_file_content(str(target), 'a\nb\nc\nd\ne\n')
    assert result['ok'] is True
    assert result['diff'] != ''
    assert '---' in result['diff'] or '+++' in result['diff']


def test_write_file_returns_created_flag(tmp_path):
    new_target = tmp_path / 'new2.py'
    result = write_file_content(str(new_target), 'x')
    assert result['ok'] is True
    assert result['created'] is True

    existing = tmp_path / 'existing.py'
    existing.write_text('y', encoding='utf-8')
    result2 = write_file_content(str(existing), 'z')
    assert result2['ok'] is True
    assert result2['created'] is False


def test_write_file_truncates_long_diff(tmp_path):
    target = tmp_path / 'long.py'
    old_lines = '\n'.join(f'old{i}' for i in range(5000)) + '\n'
    new_lines = '\n'.join(f'new{i}' for i in range(5000)) + '\n'
    target.write_text(old_lines, encoding='utf-8')
    result = write_file_content(str(target), new_lines)
    assert result['ok'] is True
    assert len(result['diff']) <= MAX_DIFF_LENGTH + 50
    assert 'truncated' in result['diff']


# ── edit_file 功能测试 ───────────────────────────────────────

def test_edit_file_exact_single_match(tmp_path):
    target = tmp_path / 'e.py'
    target.write_text('def foo():\n    return 1\n', encoding='utf-8')
    result = edit_file_content(str(target), 'return 1', 'return 2')
    assert result['ok'] is True
    assert result['replacements'] == 1
    content = target.read_text(encoding='utf-8')
    assert 'return 2' in content
    assert 'return 1' not in content


def test_edit_file_exact_multiple_replace_all(tmp_path):
    target = tmp_path / 'm.py'
    target.write_text('a a a', encoding='utf-8')
    result = edit_file_content(str(target), 'a', 'b', replace_all=True)
    assert result['ok'] is True
    assert result['replacements'] == 3
    assert target.read_text(encoding='utf-8') == 'b b b'


def test_edit_file_exact_multiple_without_replace_all_errors(tmp_path):
    target = tmp_path / 'm2.py'
    target.write_text('a a a', encoding='utf-8')
    result = edit_file_content(str(target), 'a', 'b')
    assert result['ok'] is False
    assert '3' in result['error']
    assert 'context' in result['error']


def test_edit_file_not_found_errors(tmp_path):
    target = tmp_path / 'nf.py'
    target.write_text('hello world', encoding='utf-8')
    result = edit_file_content(str(target), 'nonexistent', 'x')
    assert result['ok'] is False
    assert 'not found' in result['error']


def test_edit_file_fuzzy_match_tolerates_indentation(tmp_path):
    target = tmp_path / 'fz.py'
    # 文件用 4 空格缩进
    target.write_text('def foo():\n    return 1\n', encoding='utf-8')
    # old_string 用 2 空格缩进（精确不匹配，strip 后匹配）
    result = edit_file_content(str(target), 'def foo():\n  return 1', 'def foo():\n  return 2')
    assert result['ok'] is True
    assert result['replacements'] == 1
    assert 'return 2' in target.read_text(encoding='utf-8')


def test_edit_file_fuzzy_multiple_without_replace_all_errors(tmp_path):
    target = tmp_path / 'fzm.py'
    target.write_text('foo\nbar\nfoo\nbar\n', encoding='utf-8')
    # old_string 带前导空格，精确不匹配；strip 后 'foo' 有 2 处
    result = edit_file_content(str(target), '  foo', 'baz')
    assert result['ok'] is False
    assert 'fuzzy' in result['error']
    assert '2' in result['error']


def test_edit_file_identical_strings_errors(tmp_path):
    target = tmp_path / 'id.py'
    target.write_text('hello', encoding='utf-8')
    result = edit_file_content(str(target), 'hello', 'hello')
    assert result['ok'] is False
    assert 'identical' in result['error']


def test_edit_file_nonexistent_file_errors(tmp_path):
    result = edit_file_content(str(tmp_path / 'nope.py'), 'a', 'b')
    assert result['ok'] is False
    assert 'does not exist' in result['error']


def test_edit_file_directory_errors(tmp_path):
    result = edit_file_content(str(tmp_path), 'a', 'b')
    assert result['ok'] is False
    assert 'directory' in result['error']


def test_edit_file_binary_extension_errors(tmp_path):
    target = tmp_path / 'x.png'
    target.write_bytes(b'\x89PNG\r\n')
    result = edit_file_content(str(target), 'a', 'b')
    assert result['ok'] is False
    assert 'binary' in result['error']


def test_edit_file_empty_old_string_errors(tmp_path):
    target = tmp_path / 'empty.py'
    target.write_text('hello', encoding='utf-8')
    result = edit_file_content(str(target), '', 'b')
    assert result['ok'] is False
    assert 'empty' in result['error']


def test_edit_file_preserves_bom_and_newline(tmp_path):
    target = tmp_path / 'bomcrlf.py'
    with open(target, 'wb') as f:
        f.write(b'\xef\xbb\xbfline1\r\nline2\r\n')
    result = edit_file_content(str(target), 'line1', 'LINE1')
    assert result['ok'] is True
    data = target.read_bytes()
    assert data.startswith(b'\xef\xbb\xbf')
    assert b'\r\n' in data


def test_edit_file_returns_unified_diff(tmp_path):
    target = tmp_path / 'ud.py'
    target.write_text('a\nb\nc\n', encoding='utf-8')
    result = edit_file_content(str(target), 'b', 'B')
    assert result['ok'] is True
    assert '--- a/' in result['diff']
    assert '+++ b/' in result['diff']


def test_edit_file_exact_match_overrides_fuzzy(tmp_path):
    """精确匹配 1 处时，即使 strip 后有多处，也只走精确分支（replacements=1）。"""
    target = tmp_path / 'eo.py'
    target.write_text('foo\nbar\n  foo\n  bar\n', encoding='utf-8')
    # old_string='foo\nbar' 精确匹配 1 处（第 2 处是 '  foo\n  bar'，子串不连续）
    # 但 strip 后有 2 处整行匹配 —— 验证精确优先，不降级到模糊
    result = edit_file_content(str(target), 'foo\nbar', 'baz')
    assert result['ok'] is True
    assert result['replacements'] == 1
    content = target.read_text(encoding='utf-8')
    assert content.startswith('baz')
    assert '  foo\n  bar' in content  # 第二处未被替换


def test_edit_file_replace_all_with_fuzzy(tmp_path):
    target = tmp_path / 'raf.py'
    target.write_text('  foo\nbar\n  foo\n', encoding='utf-8')
    # old_string='foo' 精确不匹配（文件里是 '  foo'）；strip 后 2 处
    result = edit_file_content(str(target), 'foo', 'baz', replace_all=True)
    assert result['ok'] is True
    assert result['replacements'] == 2
    content = target.read_text(encoding='utf-8')
    assert 'baz' in content
    assert 'foo' not in content
