"""version.py 版本号解析与更新判断测试（方案 §4.2 全矩阵）。"""

import pytest

from version import VERSION, has_update, is_prerelease, parse_version


class TestParseVersion:
    @pytest.mark.parametrize(
        'raw,expected',
        [
            ('1.2.3', (1, 2, 3)),
            ('1.2', (1, 2, 0)),  # 不足 3 段补零
            ('v1.2.3', (1, 2, 3)),  # 前导 v/V 剥离
            ('V1.2.3', (1, 2, 3)),
            ('1.9.9', (1, 9, 9)),
            ('1.10.0', (1, 10, 0)),  # 整数逐段比较：1.10.0 > 1.9.9
            (' 1.2.3 ', (1, 2, 3)),
            ('1.beta.0', (1, -1, 0)),  # 段内无数字 → -1，低于任何正式段
            ('1.1.0-beta', (1, 1, 0)),  # '0-beta' 截数字前缀 → 与正式版相等
            ('1.1.0.1', (1, 1, 0)),  # 4 段截断
            ('1.1.0.beta', (1, 1, 0)),
            ('', (-1, 0, 0)),  # 畸形字符串 → 低于任何正式版
            ('x.y.z', (-1, -1, -1)),
        ],
    )
    def test_parse(self, raw, expected):
        assert parse_version(raw) == expected

    def test_segment_compare_is_numeric(self):
        # 纯整数逐段比较而非字符串排序
        assert parse_version('1.9.9') < parse_version('1.10.0')
        assert parse_version('1.2') < parse_version('1.2.3')


class TestIsPrerelease:
    @pytest.mark.parametrize(
        'raw,expected',
        [
            ('1.2.3', False),
            ('v1.2.3', False),
            ('1.3.0-beta', True),
            ('1.3.0-rc.1', True),
            ('1.3.0+meta', True),  # 构建元数据同视为预发布
        ],
    )
    def test_prerelease_detection(self, raw, expected):
        assert is_prerelease(raw) is expected


class TestHasUpdate:
    # 注意：以下用例锚定 VERSION == '0.2.0'（发布起点）；升级/降级相对语义
    # 不随具体版本号变化，若将来修改 VERSION 需同步调整这几组字面值。
    @pytest.mark.parametrize(
        'latest,expected',
        [
            (VERSION, False),  # 同版本
            ('0.1.9', False),  # 远端低于本地（回滚场景）
            ('0.3.0', True),  # 升级
            ('1.0.0', True),
            ('v0.3.0', True),  # 前导 v 正常比较
            ('v0.2.0-beta', False),  # 预发布一律不提示
            ('v0.3.0-beta', False),  # 即使段值更高，预发布也不提示
            ('v0.3.0+meta', False),
            ('0.2.0.1', False),  # 4 段截断为 (0,2,0) 与本地相等 → 不误判
            ('0.beta.0', False),  # 畸形低于任何正式版
            ('', False),
        ],
    )
    def test_update_decision(self, latest, expected):
        assert has_update(latest) is expected

    def test_local_version_is_three_segments(self):
        # 发布约定：版本号一律 X.Y.Z（≤3 段）
        assert len(VERSION.split('.')) == 3
        assert not is_prerelease(VERSION)
