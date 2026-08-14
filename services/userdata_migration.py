"""一次性用户数据迁出：插件/技能状态与用户导入技能从版本目录复制到部署根。

触发位置在应用启动序列（server_quart 的 before_serving 钩子，先于技能/插件加载）。
迁移源 = 上一已知版本目录（versions.json 的 last_good ?? current）的 _internal；
无法定位时回退资源根。复制语义为**仅补缺**——目标已存在则跳过、不覆盖，
保证失败重试幂等且不会用旧版本中的陈旧数据覆盖部署根的新状态。
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import sys
from typing import Any, Dict, List, Optional, Set

from zaowu_paths import get_project_root, get_resource_root

from services.versions_config import read_versions_config

logger = logging.getLogger('services.userdata_migration')

MIGRATION_MARKER = '.userdata_migrated'

_PLUGIN_STATE_FILENAME = '.plugin_state.json'
_SKILL_STATE_FILENAME = '.skill_state.json'


def migration_marker_path(root: str) -> str:
    return os.path.join(root, MIGRATION_MARKER)


def has_migration_marker(root: str) -> bool:
    """迁移是否已完成（旧版本清理的前置守卫也以此为准）。"""
    return os.path.isfile(migration_marker_path(root))


def migration_source(root: str) -> Optional[str]:
    """上一已知版本目录的 _internal（存在才返回）。

    frozen：versions/<last_good ?? current>/_internal；
    回退 get_resource_root()（frozen 扁平布局 / 开发模式）。
    """
    if getattr(sys, 'frozen', False):
        cfg = read_versions_config(root)
        prev = cfg.get('last_good') or cfg.get('current')
        if prev:
            cand = os.path.join(root, 'versions', str(prev), '_internal')
            if os.path.isdir(cand):
                return cand
    return get_resource_root()


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _copy2_if_missing(src: str, dst: str) -> bool:
    """补缺复制单个文件；目标已存在跳过。返回是否实际复制。"""
    if not os.path.isfile(src) or os.path.exists(dst):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copytree_if_missing(src: str, dst: str) -> bool:
    """补缺复制目录（整体跳过）；目标已存在不覆盖。返回是否实际复制。"""
    if not os.path.isdir(src) or os.path.exists(dst):
        return False
    shutil.copytree(src, dst)
    return True


def _user_skill_names(source: str) -> Set[str]:
    """源状态文件中显式管理过的技能名（enabled ∪ disabled，排除 deleted）。

    用户导入的技能必然写入 enabled；内置技能默认不入名单，因此该集合
    可作为「用户导入技能目录」的判别依据（现有代码无 origin 标记）。
    """
    state_path = os.path.join(source, 'agent_modules', 'skills', _SKILL_STATE_FILENAME)
    state = _read_json(state_path)
    names = set(state.get('enabled') or [])
    names.update(state.get('disabled') or [])
    names.difference_update(state.get('deleted') or [])
    return {str(n) for n in names}


def _copy_skill_dirs(source: str, root: str) -> List[str]:
    """复制用户导入的技能目录（仅补缺），返回复制的目录名列表。"""
    src_skills = os.path.join(source, 'agent_modules', 'skills')
    if not os.path.isdir(src_skills):
        return []
    user_names = _user_skill_names(source)
    copied: List[str] = []
    for entry in os.scandir(src_skills):
        if not entry.is_dir(follow_symlinks=False):
            continue
        name = entry.name
        if name.startswith('.') or name.startswith('_'):
            continue
        if name not in user_names:
            continue
        if _copytree_if_missing(entry.path, os.path.join(root, 'skills', name)):
            copied.append(name)
    return copied


def migrate_userdata(root: str, source: str) -> bool:
    """执行一次迁移；任何异常记录日志并返回 False（不阻断启动，下次重试）。

    成功（含空复制）后写迁移标记。返回是否成功。
    """
    try:
        copied = 0
        if _copy2_if_missing(
            os.path.join(source, 'plugins', _PLUGIN_STATE_FILENAME),
            os.path.join(root, _PLUGIN_STATE_FILENAME),
        ):
            copied += 1
        if _copy2_if_missing(
            os.path.join(source, 'agent_modules', 'skills', _SKILL_STATE_FILENAME),
            os.path.join(root, 'skills', _SKILL_STATE_FILENAME),
        ):
            copied += 1
        copied += len(_copy_skill_dirs(source, root))

        marker = migration_marker_path(root)
        tmp = marker + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(
                {'migrated_at': datetime.datetime.now().isoformat(timespec='seconds')},
                f,
                ensure_ascii=False,
                indent=2,
            )
        os.replace(tmp, marker)
        logger.info(
            'userdata migration done from %s (%d item(s) copied)',
            source,
            copied,
        )
        return True
    except Exception:
        logger.exception('userdata migration failed from %s; will retry next start', source)
        return False


def run_migration_if_needed(root: str | None = None) -> None:
    """启动钩子入口：根目录无迁移标记时执行迁移。

    任何异常记录日志后吞掉——迁移失败不阻断启动，下次启动重试。
    """
    try:
        root = root if root is not None else get_project_root()
        if has_migration_marker(root):
            return
        source = migration_source(root)
        if source is None or not os.path.isdir(source):
            logger.warning('userdata migration source not found under %r; skipping', root)
            return
        migrate_userdata(root, source)
    except Exception:
        logger.exception('userdata migration failed; continuing')
