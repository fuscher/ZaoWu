"""versions.json（版本配置文件）的唯一读写模块。

职责划分（硬性约束，任何一方变更不得破坏对方既有格式）：
- 应用只写 ``pending``（更新请求）与读 ``last_result``；
- 启动器只写 ``current`` / ``last_good`` / ``pending→null`` / ``last_result``。

所有写入采用「写 versions.json.tmp → os.replace 原子替换」，任何时刻文件内容完整。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from zaowu_paths import get_project_root

VERSIONS_FILENAME = 'versions.json'


def versions_path(root: str | None = None) -> str:
    return os.path.join(root if root is not None else get_project_root(), VERSIONS_FILENAME)


def read_versions_config(root: str | None = None) -> Dict[str, Any]:
    """宽容读：文件缺失或损坏返回空 dict（调用方按默认值处理）。"""
    try:
        with open(versions_path(root), 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def write_versions_config(data: Dict[str, Any], root: str | None = None) -> None:
    """原子写 versions.json（tmp + os.replace）。

    写后 flush + fsync 落盘：apply 流程随后紧跟 os._exit(0)，进程不做清理，
    必须保证 pending 在退出前持久化。
    """
    path = versions_path(root)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
