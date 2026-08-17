"""检查更新服务（版本隔离架构的更新侧）。

端点（蓝图前缀 /api/update，注册于 server_quart）：
- GET  /check     双源并发检查；consume_only=1 时跳过网络段仅消费 last_result
- GET  /download  流式下载 + sha256 + 解压防护 → versions/vX/
- POST /apply     原子写 pending → 拉起启动器 --switch → 触发受控退出
- GET  /status    内存态进度快照（不落盘）

来源校验：download/apply/status 仅接受环回来源（局域网设备伪造请求的
威胁模型）；check 纯只读，仅 frozen 门禁。开发模式（非 frozen）一律
supported:false，不触网。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import httpx
from quart import Blueprint, jsonify, request

from version import VERSION, has_update, is_prerelease, parse_version
from zaowu_paths import get_project_root, get_resource_root

from services.versions_config import read_versions_config, write_versions_config
from services.userdata_migration import has_migration_marker

logger = logging.getLogger('zaowu.routes.update')

update_bp = Blueprint('update', __name__)

BASE_DIR = get_project_root()
VERSIONS_DIR = os.path.join(BASE_DIR, 'versions')
STAGING_DIR = os.path.join(VERSIONS_DIR, '.staging')
LAUNCHER_NAME = 'ZaoWuLauncher.exe'

# 检查源：静态 version.json 三源（GitHub raw / jsDelivr CDN / Gitee raw）。
# ZAOWU_UPDATE_SOURCES=url1,url2 可整体覆盖（本地模拟与调试专用）。
_DEFAULT_SOURCES = [
    'https://raw.githubusercontent.com/fuscher/ZaoWu/main/version.json',
    'https://cdn.jsdelivr.net/gh/fuscher/ZaoWu@main/version.json',
    'https://gitee.com/fuscher/ZaoWu/raw/main/version.json',
]

SOURCE_URLS = [
    u.strip()
    for u in os.environ.get('ZAOWU_UPDATE_SOURCES', '').split(',')
    if u.strip()
] or _DEFAULT_SOURCES

# 解压防护阈值
_MAX_ENTRIES = 20000
_MAX_TOTAL_SIZE = 1 << 30  # 1GB
_MAX_SEGMENTS_RE = re.compile(r'^[vV]?\d+(\.\d+){0,2}$')  # 目录名白名单：vX.Y.Z ≤3 段

# 下载互斥（进程级；单进程 Quart 假设与 skill_loader 一致）。
# 重复点击快速失败（409），不排队。
_download_lock = asyncio.Lock()

# versions.json 写锁：_consume_last_result 与 apply 写同一文件，
# 串行化防并发读改写覆盖。
_config_lock = asyncio.Lock()

# 内存态下载状态（不落盘，勿增实体）
_status: Dict[str, Any] = {'state': 'idle', 'progress': 0, 'version': None, 'error': None}


def _is_frozen() -> bool:
    """独立函数便于测试 monkeypatch。"""
    return bool(getattr(sys, 'frozen', False))


def _is_loopback(addr: Optional[str]) -> bool:
    """环回白名单；None（直调）与 '<local>'（Quart test_client 哨兵值，
    生产环境不出现）放行。IPv4-mapped IPv6 必须放行（Quart 部分绑定模式
    下 remote_addr 呈现为此形态）。"""
    if addr is None or addr == '<local>':
        return True
    return addr in {'127.0.0.1', '::1', '::ffff:127.0.0.1'}


def _require_local(addr: Optional[str] = None):
    """非环回来源拒绝；满足时返回 None。addr 缺省取 request.remote_addr，
    显式传入便于单元测试（Quart test_request_context 不支持 remote_addr 覆盖）。"""
    if not _is_loopback(addr if addr is not None else request.remote_addr):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    return None


class UpdateError(Exception):
    """更新流程的预期失败（映射为 400 响应）。"""


# ── 检查 ──────────────────────────────────────────────────────────────

def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(10.0, connect=10.0))


async def _fetch_source_json(client: httpx.AsyncClient, url: str) -> Optional[Dict[str, Any]]:
    """单源读取 version.json；任何失败返回 None。"""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning('update source %s failed: %s', url, exc)
        return None
    return data if isinstance(data, dict) else None


async def _check_latest() -> Dict[str, Any]:
    """双源并发、取版本号较大者；全源失败 → error。

    返回 {hasUpdate, latest, notes, assets, error}；latest 为预发布时
    过滤为无更新（has_update 双保险，远端过滤在发布侧）。
    """
    client = _make_client()
    try:
        results = await asyncio.gather(
            *(_fetch_source_json(client, u) for u in SOURCE_URLS),
            return_exceptions=True,
        )
    finally:
        await client.aclose()

    best_version: Optional[str] = None
    best: Optional[Dict[str, Any]] = None
    for r in results:
        if isinstance(r, BaseException) or not r:
            continue
        version = str(r.get('version') or '')
        if not version or is_prerelease(version):
            continue
        if best_version is None or parse_version(version) > parse_version(best_version):
            best_version = version
            best = r

    if best is None:
        return {'hasUpdate': False, 'latest': None, 'notes': None, 'assets': None, 'error': 'update_unavailable'}

    assets = best.get('assets') or {}
    win64 = assets.get('win64') if isinstance(assets, dict) else None
    if not isinstance(win64, dict) or not win64.get('urls'):
        # 平台不适用（无 win64 资产）→ 按无更新处理
        return {'hasUpdate': False, 'latest': best_version, 'notes': best.get('notes'), 'assets': None, 'error': None}

    return {
        'hasUpdate': has_update(best_version),
        'latest': best_version,
        'notes': best.get('notes'),
        'assets': win64,
        'error': None,
    }


async def _consume_last_result() -> Optional[str]:
    """一次性消费 last_result：读后置 null 写回；缺失/损坏返回 None。"""
    async with _config_lock:
        cfg = read_versions_config(BASE_DIR)
        if not cfg or cfg.get('last_result') is None:
            return None
        result = cfg['last_result']
        cfg['last_result'] = None
        try:
            write_versions_config(cfg, BASE_DIR)
        except OSError as exc:
            logger.warning('failed to consume last_result: %s', exc)
        return result


async def _cleanup_old_versions() -> None:
    """切换成功后异步清理 versions/ 下除 current/last_good/.staging 外的目录。

    前置守卫：用户数据迁移标记缺失时跳过——旧版本 _internal 仍是迁移失败
    时用户数据的唯一副本。失败静默，下次更新时再试。
    """
    try:
        if not has_migration_marker(BASE_DIR):
            logger.info('migration marker missing; skipping old version cleanup')
            return
        cfg = read_versions_config(BASE_DIR)
        keep = {cfg.get('current'), cfg.get('last_good'), '.staging'}
        if not os.path.isdir(VERSIONS_DIR):
            return
        import send2trash
        for entry in os.scandir(VERSIONS_DIR):
            if entry.name in keep or entry.name.startswith('.'):
                continue
            if entry.is_dir(follow_symlinks=False):
                send2trash.send2trash(entry.path)
                logger.info('sent old version to trash: %s', entry.name)
    except Exception:
        logger.exception('old version cleanup failed; will retry next update')


# ── 下载 ──────────────────────────────────────────────────────────────

async def _download_stream(client: httpx.AsyncClient, url: str, dest: str, expected_size: Optional[int]) -> int:
    """流式下载到 dest，返回总字节数；失败抛异常（回退下一源）。"""
    total = 0
    async with client.stream('GET', url) as resp:
        resp.raise_for_status()
        length_header = resp.headers.get('content-length')
        total_size = int(length_header) if length_header and length_header.isdigit() else (expected_size or 0)
        with open(dest, 'wb') as f:
            async for chunk in resp.aiter_bytes():
                f.write(chunk)
                total += len(chunk)
                if total_size:
                    _status['progress'] = min(99, int(total * 100 / total_size))
    if total == 0:
        raise UpdateError('empty download')
    return total


async def _download_with_fallback(urls: List[str], dest: str, expected_size: Optional[int]) -> int:
    """按序尝试 URL，任一成功即止；全部失败抛 UpdateError。"""
    client = _make_client()
    try:
        last_error = ''
        for url in urls:
            try:
                return await _download_stream(client, url, dest, expected_size)
            except Exception as exc:
                last_error = str(exc)
                logger.warning('download source failed, trying next: %s (%s)', url, exc)
        raise UpdateError(f'all download sources failed: {last_error or "unknown"}')
    finally:
        await client.aclose()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().lower()


def _validate_zip(zf: zipfile.ZipFile) -> None:
    """解压防护（纯元数据预检，不解压数据）：
    - 路径穿越（.. / 绝对路径 / 盘符）
    - zip 炸弹（条目数、file_size 总和）
    - 夹带状态文件（.skill_state.json / .plugin_state.json）
    - 未预知插件目录（与当前资源根 plugins/ 清单比对，防误打包的第三方插件被执行）
    """
    infos = zf.infolist()
    if len(infos) > _MAX_ENTRIES:
        raise UpdateError(f'too many entries: {len(infos)}')
    if sum(i.file_size for i in infos) > _MAX_TOTAL_SIZE:
        raise UpdateError('unpacked size exceeds 1GB')

    resource_plugins = os.path.join(get_resource_root(), 'plugins')
    known_plugins = set()
    if os.path.isdir(resource_plugins):
        known_plugins = {e.name for e in os.scandir(resource_plugins) if e.is_dir()}

    for info in infos:
        name = info.filename.replace('\\', '/')
        segments = name.split('/')
        # 路径穿越：绝对路径 / 盘符 / 任意段为 '..'（含中间段，如 a/../b）
        if name.startswith('/') or (len(name) > 1 and name[1] == ':') or '..' in segments:
            raise UpdateError(f'path traversal rejected: {name!r}')
        lower = name.lower()
        if lower.endswith('/'):
            continue
        if '.skill_state.json' in lower or '.plugin_state.json' in lower:
            raise UpdateError(f'bundled state file rejected: {name!r}')
        if len(segments) >= 3 and segments[0] == '_internal' and segments[1] == 'plugins':
            # plugins/ 根下的散文件（如 PLUGIN_DEV_GUIDE.md，路径恰好 3 段）
            # 不是插件目录，不参与"未知插件目录"校验；目录条目已在上方
            # lower.endswith('/') 分支跳过，此处只需按段数区分。
            if len(segments) == 3:
                continue
            plugin_dir = segments[2]
            if plugin_dir not in known_plugins:
                raise UpdateError(f'unknown plugin directory rejected: {plugin_dir!r}')


def _version_dir(version: str) -> str:
    """版本目录名统一为 vX.Y.Z（与首装/bootstrap 的 v0 前缀风格一致）。

    远端 version 字段通常无 v 前缀；若已带 v/vV 前缀则保持原样，防重复。"""
    return version if version[:1].lower() == 'v' else 'v' + version


def _extract_zip(zip_path: str, dest_dir: str) -> None:
    """防护校验通过后解压至 dest_dir（目录名 vX.Y.Z，先过白名单校验，
    不取自 zip 内路径）。"""
    dir_name = os.path.basename(dest_dir.rstrip('/\\'))
    if not _MAX_SEGMENTS_RE.match(dir_name):
        raise UpdateError(f'invalid version for directory name: {dir_name!r}')
    with zipfile.ZipFile(zip_path) as zf:
        _validate_zip(zf)
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir)
        os.makedirs(dest_dir, exist_ok=True)
        zf.extractall(dest_dir)


# ── 端点 ──────────────────────────────────────────────────────────────

@update_bp.route('/check', methods=['GET'])
async def check():
    consume_only = request.args.get('consume_only') == '1'
    last_result = await _consume_last_result()
    if last_result == 'ok':
        # 切换成功的后台清理（fire-and-forget，任务内部整体容错）
        asyncio.create_task(_cleanup_old_versions())

    base = {
        'supported': _is_frozen(),
        'current': VERSION,
        'hasUpdate': False,
        'latest': None,
        'notes': None,
        'assets': None,
        'lastResult': last_result,
        'error': None,
    }
    if consume_only or not _is_frozen():
        # 挂载时静默消费：不发任何外部请求；开发模式不触网
        return jsonify(base)

    info = await _check_latest()
    base.update(info)
    return jsonify(base)


@update_bp.route('/download', methods=['GET'])
async def download():
    guard = _require_local()
    if guard is not None:
        return guard
    if not _is_frozen():
        return jsonify({'ok': False, 'error': 'unsupported'}), 400
    if _download_lock.locked():
        return jsonify({'ok': False, 'error': 'download_in_progress'}), 409

    async with _download_lock:
        _status.update({'state': 'downloading', 'progress': 0, 'version': None, 'error': None})
        try:
            # 重新检查（不信任前端参数，保证幂等与安全）
            info = await _check_latest()
            if info.get('error'):
                raise UpdateError(info['error'])
            if not info.get('hasUpdate') or not info.get('assets'):
                raise UpdateError('no update available')
            version = info['latest']
            assets = info['assets']
            urls = list(assets.get('urls') or [])
            sha256_expected = str(assets.get('sha256') or '').lower()
            size = assets.get('size')
            if not urls or not sha256_expected:
                raise UpdateError('incomplete asset metadata')

            # 清理上次失败残留：.staging 清理失败（文件占用）即中止，防残留合并
            if os.path.exists(STAGING_DIR):
                shutil.rmtree(STAGING_DIR)
            os.makedirs(STAGING_DIR, exist_ok=True)

            # 清理之前下载但未切换的版本目录（防磁盘累积，与 _cleanup_old_versions 对称）
            target_vdir = _version_dir(version)
            if os.path.isdir(VERSIONS_DIR):
                cfg = read_versions_config(BASE_DIR)
                keep = {cfg.get('current'), cfg.get('last_good'), '.staging', target_vdir}
                for entry in os.scandir(VERSIONS_DIR):
                    if entry.name in keep or entry.name.startswith('.'):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        shutil.rmtree(entry.path, ignore_errors=True)
                        logger.info('cleaned up unused version dir: %s', entry.name)

            zip_path = os.path.join(STAGING_DIR, f'ZaoWu-{version}-win64.zip')
            try:
                expected_size = int(size) if size else None
            except (ValueError, TypeError):
                expected_size = None
            await _download_with_fallback(urls, zip_path, expected_size)

            actual = await asyncio.to_thread(_sha256_file, zip_path)
            if actual != sha256_expected:
                raise UpdateError('checksum mismatch')

            version_dir = _version_dir(version)
            dest_dir = os.path.join(VERSIONS_DIR, version_dir)
            await asyncio.to_thread(_extract_zip, zip_path, dest_dir)

            _status.update({'state': 'ready', 'progress': 100, 'version': version_dir, 'error': None})
            logger.info('update package ready: %s', version)
            return jsonify({'ok': True, 'version': version})
        except UpdateError as exc:
            if os.path.exists(STAGING_DIR):
                shutil.rmtree(STAGING_DIR, ignore_errors=True)
            _status.update({'state': 'idle', 'version': None, 'error': str(exc)})
            return jsonify({'ok': False, 'error': str(exc)}), 400
        except Exception:
            if os.path.exists(STAGING_DIR):
                shutil.rmtree(STAGING_DIR, ignore_errors=True)
            logger.exception('download failed')
            _status.update({'state': 'idle', 'version': None, 'error': 'internal_error'})
            return jsonify({'ok': False, 'error': 'internal_error'}), 500


@update_bp.route('/apply', methods=['POST'])
async def apply():
    guard = _require_local()
    if guard is not None:
        return guard
    if not _is_frozen():
        return jsonify({'ok': False, 'error': 'unsupported'}), 400

    from server_quart import _shutdown_event

    async with _config_lock:
        cfg = read_versions_config(BASE_DIR)
        if cfg.get('pending'):
            pending_dir = os.path.join(VERSIONS_DIR, cfg['pending'])
            if not os.path.isdir(pending_dir):
                # 版本目录不存在：上次切换失败留下残留 pending，清除后允许重试
                logger.warning('stale pending %r cleared (version dir missing)', cfg['pending'])
                cfg['pending'] = None
                write_versions_config(cfg, BASE_DIR)
            elif _shutdown_event.is_set():
                # shutdown 已触发 → 上次 apply 成功，切换确在进行中，幂等返回
                return jsonify({'ok': True})
            else:
                # pending + 目录存在 + shutdown 未触发 → Popen/启动器失败残留，重新 spawn
                # 若 _status 有更新版本（用户重新下载了），升级 pending
                new_ver = _status.get('version')
                if (new_ver and new_ver != cfg['pending']
                        and _status.get('state') == 'ready'
                        and os.path.isdir(os.path.join(VERSIONS_DIR, new_ver))):
                    logger.warning('upgrading pending %r → %r', cfg['pending'], new_ver)
                    cfg['pending'] = new_ver
                    write_versions_config(cfg, BASE_DIR)
                else:
                    logger.warning('re-spawning launcher for pending %r (shutdown not set)', cfg['pending'])
            # stale 清除后 fall-through 到下方正常流程；re-spawn 也 fall-through

        # 正常首次 apply 路径：确定版本、写 pending
        if not cfg.get('pending'):
            version = _status.get('version')
            if _status.get('state') != 'ready' or not version:
                return jsonify({'ok': False, 'error': 'not_ready'}), 400
            if not os.path.isdir(os.path.join(VERSIONS_DIR, version)):
                return jsonify({'ok': False, 'error': 'package_missing'}), 400
            cfg['pending'] = version
            write_versions_config(cfg, BASE_DIR)

    # spawn 启动器 + 触发退出（锁外执行，避免持锁启动子进程）
    pending_version = cfg.get('pending')
    launcher_path = os.path.join(BASE_DIR, LAUNCHER_NAME)
    if not os.path.isfile(launcher_path):
        return jsonify({'ok': False, 'error': 'launcher_missing'}), 500
    subprocess.Popen(
        [launcher_path, '--switch', '--pid', str(os.getpid())],
        cwd=BASE_DIR,
        close_fds=True,
    )

    # 触发受控退出（函数内导入避免 server_quart ↔ routes.update 循环导入；
    # apply 是同一事件循环内的 async handler，set() 线程安全）。
    # Hypercorn 优雅关闭不取消在途请求，本响应必达前端。
    _shutdown_event.set()
    return jsonify({'ok': True})


@update_bp.route('/status', methods=['GET'])
async def status():
    guard = _require_local()
    if guard is not None:
        return guard
    return jsonify(dict(_status))
