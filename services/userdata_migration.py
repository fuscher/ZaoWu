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
from typing import Any, Dict, List, Optional, Set, Tuple

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


# ── 每启动插件救援（独立于一次性 migrate_userdata）───────────────────
#
# 为什么独立：migrate_userdata 即便复制 0 项也写 .userdata_migrated 标记，
# 而 run_migration_if_needed 见标记即返回。现有 v0.2.0 部署首启早已写过标记，
# 把插件迁出塞进该函数意味着修复发布后老部署首启直接跳过救援 → 用户插件在 UI
# 消失 → 下次更新 last_good 滚动后旧版本目录进回收站 → 文件彻底丢失。
# 救援因此每次启动执行、幂等、不依赖标记（详见 docs/plugin-update-fix-plan.md §3.5）。


def _builtin_plugin_names() -> Set[str]:
    """当前（新）版本资源根 plugins/ 下的目录名（名字兜底信号，非唯一依据）。"""
    p = os.path.join(get_resource_root(), 'plugins')
    if not os.path.isdir(p):
        return set()
    return {e.name for e in os.scandir(p) if e.is_dir(follow_symlinks=False)}


def _is_builtin_plugin(entry_path: str, current_builtins: Set[str]) -> bool:
    """内置判定：manifest 标记为权威 + 当前版本内置名单兜底。"""
    manifest = _read_json(os.path.join(entry_path, 'manifest.json'))
    if manifest.get('builtin') is True:
        return True
    return os.path.basename(entry_path) in current_builtins


def _plugin_candidate_files(entry_path: str) -> bool:
    """候选判定：与 loader.discover 完全一致（manifest.json 且 __init__.py 齐备）。"""
    return (os.path.isfile(os.path.join(entry_path, 'manifest.json'))
            and os.path.isfile(os.path.join(entry_path, '__init__.py')))


def _uninstalled_at_root(dest_root: str, base: str) -> bool:
    """部署根是否存在该插件的卸载态（P.disabled 或 P.disabled.N）。"""
    if not os.path.isdir(dest_root):
        return False
    for entry in os.scandir(dest_root):
        if entry.name == base + '.disabled' or entry.name.startswith(base + '.disabled.'):
            return True
    return False


def _rescue_sources(root: str) -> List[str]:
    """救援扫描源：versions/ 下全部版本目录（新→旧）+ 资源根回退。

    不能只取 migration_source（= last_good）：隔版本安装的插件躺在更早
    的目录里，而修复版首启时它仍在磁盘（本次更新清理尚未触发）。
    新→旧排序保证「每个插件名的最高版本实例」先被登记（两遍扫描第一遍）。
    """
    from version import parse_version   # 与更新检查同一解析器（vX.Y.Z，3 段补零）

    sources: List[str] = []
    versions_dir = os.path.join(root, 'versions')
    if os.path.isdir(versions_dir):
        entries = [e.name for e in os.scandir(versions_dir)
                   if e.is_dir(follow_symlinks=False) and not e.name.startswith('.')]
        entries.sort(key=parse_version, reverse=True)
        for name in entries:
            internal = os.path.join(versions_dir, name, '_internal')
            if os.path.isdir(internal):
                sources.append(internal)
    fallback = get_resource_root()      # frozen 扁平布局 / 开发模式（last_good 缺失时的回退）
    if fallback not in sources and os.path.isdir(fallback):
        sources.append(fallback)
    return sources


def _rescue_plan(sources: List[str], root: str) -> Dict[str, str]:
    """两遍扫描汇总「每个插件名的权威实例」→ {name: 源路径}。

    第一遍：sources 已按新→旧排序，每个插件名取**最高版本目录**中出现的
    实例（P = 启用，P.disabled / P.disabled.N = 已卸载——后者经包含判定归一
    到基名；同一目录内两者并存时 P 优先——目录名排序保证先登记）。最高版本
    实例为卸载态 → 不救出（防止低版本启用副本跨版本复活）；为启用态 → 继续。
    不做全局黑名单：「低版本卸载、高版本重装启用」时高版本 P 即权威，正常入计划。
    第二遍：过滤部署根卸载态、非插件目录（候选文件不齐）、内置插件。
    """
    dest_root = os.path.join(root, 'plugins')
    newest: Dict[str, Tuple[bool, str]] = {}   # name -> (enabled?, path)
    for source in sources:
        src_plugins = os.path.join(source, 'plugins')
        if not os.path.isdir(src_plugins):
            continue
        for entry in sorted(os.scandir(src_plugins), key=lambda e: e.name):
            if not entry.is_dir(follow_symlinks=False):
                continue          # .plugin_state.json 等文件跳过（状态另行复制）
            name = entry.name
            if name.startswith('.') or name.startswith('_'):
                continue          # 与 loader.discover 的跳过规则一致
            disabled = '.disabled' in name   # 插件名受 ^[A-Za-z0-9_]+$ 约束不含 '.'，
                                            # 故含 '.disabled' 的目录名必为卸载产物
                                            # （覆盖 P.disabled 与 P.disabled.N 重名递增）
            base = name.split('.disabled', 1)[0] if disabled else name
            if base in newest:
                continue          # 更高版本目录已给出权威状态，低版本实例忽略
            newest[base] = (not disabled, entry.path)

    builtins = _builtin_plugin_names()
    plan: Dict[str, str] = {}
    for base, (enabled, path) in newest.items():
        if not enabled:
            continue              # 最高版本实例是 P.disabled → 用户已卸载
        if _uninstalled_at_root(dest_root, base):
            continue              # 部署根卸载态（修复版上卸载）优先级最高
        if not _plugin_candidate_files(path):
            continue              # 非插件目录（候选文件不齐）
        if _is_builtin_plugin(path, builtins):
            continue              # 内置插件（含新版本已删除的内置），不救援
        plan[base] = path
    return plan


def rescue_user_plugins(root: str) -> int:
    """每次启动执行：按权威状态救援 versions/ 下的用户插件到部署根。

    必须独立于一次性 migrate_userdata（该函数受 .userdata_migrated 标记
    守卫，而老部署首启已写过标记）；本函数幂等、开销极小——补缺复制
    「命中即退」，首次救出后后续启动扫到目标已存在即跳过。
    """
    try:
        plan = _rescue_plan(_rescue_sources(root), root)
        if not plan:
            return 0
        dest_root = os.path.join(root, 'plugins')
        os.makedirs(dest_root, exist_ok=True)   # copytree 要求父目录存在
        copied = 0
        for name, path in plan.items():
            if _copytree_if_missing(path, os.path.join(dest_root, name)):
                copied += 1
                logger.info('rescued user plugin %s from %s', name, path)
        return copied
    except Exception:
        logger.exception('user plugin rescue failed; will retry next start')
        return 0
