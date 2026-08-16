"""应用版本号单一来源。

发版流程：修改 ``VERSION`` → 打包 → 打 tag → 发布附件 → 更新远端 version.json。
发布约定：版本号一律 ``X.Y.Z``（≤3 段）；带 ``-``/``+`` 后缀视为预发布，
不参与更新提示（``has_update`` 直接返回 False）。

frozen 构建下本模块随 import 图自动打进包内（编译期常量，不读磁盘）。
"""

import re

VERSION = '0.2.1'

# 发布约定：版本号 ≤3 段；第 4 段及以上（如 1.1.0.1）被截断忽略，
# 会漏报更新但不会误报——若未来启用 4 段需放宽此处与对应测试。
_MAX_SEGMENTS = 3


def parse_version(v: str) -> tuple:
    """解析版本号前 3 段为整数元组（不足补零）。

    段内取首个连续数字：'0-beta' → 0；'1.beta' → -1（低于任何正式段）。
    '1.2' → (1, 2, 0)；'v1.2.3' → (1, 2, 3)；畸形段 → -1。
    """
    parts = []
    for s in v.strip().lstrip('vV').split('.')[: _MAX_SEGMENTS]:
        m = re.match(r'\d+', s)
        parts.append(int(m.group(0)) if m else -1)
    return tuple(parts + [0] * (_MAX_SEGMENTS - len(parts)))


def is_prerelease(v: str) -> bool:
    """v1.1.0-beta / v1.1.0-rc / 构建元数据（+）视为预发布。"""
    return '-' in v or '+' in v


def has_update(latest: str) -> bool:
    """远端版本是否高于当前 VERSION；预发布一律不提示更新。"""
    if is_prerelease(latest):
        return False
    return parse_version(latest) > parse_version(VERSION)
