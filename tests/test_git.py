"""routes/git.py 纯函数单元测试。"""
import os
import types
from datetime import datetime, timezone

import pytest

from routes.git import parse_status, validate_file_paths, format_commits


# ---------------------------------------------------------------------------
# parse_status
# ---------------------------------------------------------------------------

class TestParseStatusUntracked:
    def test_untracked(self):
        result = parse_status('?? file.txt')
        assert len(result) == 1
        assert result[0] == {'path': 'file.txt', 'type': 'untracked', 'status': 'untracked'}


class TestParseStatusStaged:
    def test_staged_modified(self):
        result = parse_status('M  file.txt')
        assert len(result) == 1
        assert result[0] == {'path': 'file.txt', 'type': 'modified', 'status': 'staged'}

    def test_staged_added(self):
        result = parse_status('A  file.txt')
        assert len(result) == 1
        assert result[0] == {'path': 'file.txt', 'type': 'added', 'status': 'staged'}

    def test_staged_deleted(self):
        result = parse_status('D  file.txt')
        assert len(result) == 1
        assert result[0] == {'path': 'file.txt', 'type': 'deleted', 'status': 'staged'}


class TestParseStatusUnstaged:
    def test_unstaged_modified(self):
        # Leading-space lines: raw.strip() would trim the leading space if it's the first char.
        # In real porcelain output, multi-line strings avoid this; simulate with a preceding line.
        result = parse_status('M  a.txt\n M file.txt')
        unstaged = [c for c in result if c['status'] == 'unstaged']
        assert len(unstaged) == 1
        assert unstaged[0] == {'path': 'file.txt', 'type': 'modified', 'status': 'unstaged'}

    def test_unstaged_deleted(self):
        result = parse_status('M  a.txt\n D file.txt')
        unstaged = [c for c in result if c['status'] == 'unstaged']
        assert len(unstaged) == 1
        assert unstaged[0] == {'path': 'file.txt', 'type': 'deleted', 'status': 'unstaged'}


class TestParseStatusConflicts:
    @pytest.mark.parametrize('prefix', ['UU', 'AA', 'DD', 'UD', 'DU', 'UA', 'AU'])
    def test_conflict(self, prefix):
        result = parse_status(f'{prefix} file.txt')
        assert len(result) == 1
        assert result[0] == {'path': 'file.txt', 'type': 'conflict', 'status': 'conflict'}


class TestParseStatusRenamed:
    def test_renamed(self):
        result = parse_status('R  old.txt -> new.txt')
        assert len(result) == 1
        assert result[0] == {
            'path': 'new.txt',
            'type': 'renamed',
            'status': 'staged',
            'oldPath': 'old.txt',
        }


class TestParseStatusEdgeCases:
    def test_empty_input_returns_empty_list(self):
        assert parse_status('') == []
        assert parse_status(None) == []

    def test_mixed_statuses(self):
        raw = '?? new.txt\nM  staged.txt\n M unstaged.txt\nUU conflict.txt'
        result = parse_status(raw)
        assert len(result) == 4
        types = [(r['type'], r['status']) for r in result]
        assert ('untracked', 'untracked') in types
        assert ('modified', 'staged') in types
        assert ('modified', 'unstaged') in types
        assert ('conflict', 'conflict') in types

    def test_short_line_skipped(self):
        result = parse_status('??')
        assert result == []

    def test_both_staged_and_unstaged(self):
        """MM should produce two entries for the same file."""
        result = parse_status('MM file.txt')
        assert len(result) == 2
        assert result[0]['status'] == 'staged'
        assert result[1]['status'] == 'unstaged'


# ---------------------------------------------------------------------------
# validate_file_paths
# ---------------------------------------------------------------------------

class TestValidateFilePaths:
    def test_valid_path(self, tmp_path):
        sub = tmp_path / 'src'
        sub.mkdir()
        ok, err = validate_file_paths(str(tmp_path), ['src/file.txt'])
        assert ok is True
        assert err == ''

    def test_traversal_rejected(self, tmp_path):
        ok, err = validate_file_paths(str(tmp_path), ['../etc/passwd'])
        assert ok is False
        assert 'path traversal' in err

    def test_empty_files_list(self, tmp_path):
        ok, err = validate_file_paths(str(tmp_path), [])
        assert ok is True
        assert err == ''

    def test_dot_traversal(self, tmp_path):
        ok, err = validate_file_paths(str(tmp_path), ['../../etc/passwd'])
        assert ok is False
        assert 'path traversal' in err


# ---------------------------------------------------------------------------
# format_commits
# ---------------------------------------------------------------------------

def _make_commit(hexsha, message='commit msg', author_name='Author',
                 committed_datetime=None):
    commit = types.SimpleNamespace()
    commit.hexsha = hexsha
    commit.message = message
    commit.author = types.SimpleNamespace(name=author_name)
    commit.committed_datetime = committed_datetime or datetime(2025, 1, 1, tzinfo=timezone.utc)
    return commit


class TestFormatCommits:
    def test_basic_formatting(self):
        c = _make_commit('abc1234def567890', message='first commit')
        result = format_commits([c], local_tip=None, remote_tip=None)
        assert len(result) == 1
        assert result[0]['hash'] == 'abc1234def567890'
        assert result[0]['shortHash'] == 'abc1234'
        assert result[0]['message'] == 'first commit'

    def test_multiline_message_truncated(self):
        c = _make_commit('a' * 40, message='title\n\nbody text')
        result = format_commits([c], local_tip=None, remote_tip=None)
        assert result[0]['message'] == 'title'

    def test_author_name(self):
        c = _make_commit('b' * 40, author_name='Jane Doe')
        result = format_commits([c], local_tip=None, remote_tip=None)
        assert result[0]['author'] == 'Jane Doe'

    def test_local_tip_marked(self):
        c = _make_commit('abc1234' + '0' * 33)
        result = format_commits([c], local_tip='abc1234', remote_tip=None)
        assert result[0]['isLocalTip'] is True
        assert result[0]['isRemoteTip'] is False

    def test_remote_tip_marked(self):
        c = _make_commit('def5678' + '0' * 33)
        result = format_commits([c], local_tip=None, remote_tip='def5678')
        assert result[0]['isLocalTip'] is False
        assert result[0]['isRemoteTip'] is True

    def test_neither_tip(self):
        c = _make_commit('xxx1234' + '0' * 33)
        result = format_commits([c], local_tip='aaa1111', remote_tip='bbb2222')
        assert result[0]['isLocalTip'] is False
        assert result[0]['isRemoteTip'] is False

    def test_date_isoformat(self):
        dt = datetime(2025, 6, 15, 12, 30, 0, tzinfo=timezone.utc)
        c = _make_commit('c' * 40, committed_datetime=dt)
        result = format_commits([c], local_tip=None, remote_tip=None)
        assert '2025-06-15' in result[0]['date']

    def test_empty_commits_list(self):
        result = format_commits([], local_tip='aaa1111', remote_tip='bbb2222')
        assert result == []
