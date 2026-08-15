"""routes/update.py 更新服务测试（§10.1 清单）。

约定：monkeypatch 模块级 BASE_DIR/VERSIONS_DIR/STAGING_DIR/_status 隔离，
绝不触碰仓库根；frozen 门禁经 _is_frozen 打开；HTTP 用假 AsyncClient。
"""

import asyncio
import hashlib
import json
import os
import zipfile

import pytest

import routes.update as update
from server_quart import app

pytestmark = pytest.mark.anyio


# ── 假 HTTP 对象 ─────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'http {self.status_code}')

    def json(self):
        if self._json is None:
            raise ValueError('no json')
        return self._json


class FakeStreamResponse:
    def __init__(self, chunks, status_code=200, headers=None):
        self._chunks = chunks
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'http {self.status_code}')

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c


class FakeAsyncClient:
    """get_map: url → dict(version.json 内容) | Exception；streams: url → chunks | Exception。"""

    def __init__(self, get_map=None, streams=None):
        self.get_map = get_map or {}
        self.streams = streams or {}
        self.get_calls = []

    async def get(self, url):
        self.get_calls.append(url)
        entry = self.get_map.get(url)
        if isinstance(entry, Exception):
            raise entry
        return FakeResponse(200, entry)

    def stream(self, method, url):
        entry = self.streams.get(url)
        if isinstance(entry, Exception):
            raise entry
        return FakeStreamResponse(entry)

    async def aclose(self):
        pass


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """隔离模块级路径与内存状态，返回 tmp_path。"""
    monkeypatch.setattr(update, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(update, 'VERSIONS_DIR', str(tmp_path / 'versions'))
    monkeypatch.setattr(update, 'STAGING_DIR', str(tmp_path / 'versions' / '.staging'))
    monkeypatch.setattr(update, '_status', {'state': 'idle', 'progress': 0, 'version': None, 'error': None})
    return tmp_path


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(update, '_is_frozen', lambda: True)


@pytest.fixture
def dev_mode(monkeypatch):
    monkeypatch.setattr(update, '_is_frozen', lambda: False)


def _write_versions(tmp_path, **kw):
    data = {'schema': 1, 'current': 'v1.1.0', 'last_good': None, 'pending': None, 'last_result': None}
    data.update(kw)
    (tmp_path / 'versions.json').write_text(json.dumps(data), encoding='utf-8')


def _version_json(tmp_path, version='1.3.0', **asset_overrides):
    asset = {'urls': ['http://src-a.test/ZaoWu-1.3.0-win64.zip', 'http://src-b.test/ZaoWu-1.3.0-win64.zip'],
             'size': 100, 'sha256': 'deadbeef'}
    asset.update(asset_overrides)
    return {'version': version, 'notes': 'notes', 'assets': {'win64': asset}}


# ── 来源校验 ─────────────────────────────────────────────────────────

class TestLoopback:
    @pytest.mark.parametrize('addr,expected', [
        ('127.0.0.1', True),
        ('::1', True),
        ('::ffff:127.0.0.1', True),  # IPv4-mapped 必须放行
        (None, True),  # 直调
        ('<local>', True),  # Quart test_client 哨兵值
        ('192.168.1.5', False),
        ('10.0.0.1', False),
        ('::ffff:192.168.1.5', False),
    ])
    def test_is_loopback(self, addr, expected):
        assert update._is_loopback(addr) is expected

    @pytest.mark.parametrize('addr', ['192.168.1.5', '10.0.0.1'])
    async def test_require_local_rejects_non_loopback(self, addr):
        async with app.app_context():
            resp = update._require_local(addr)
        assert resp is not None
        assert resp[1] == 403

    async def test_require_local_allows_loopback_forms(self):
        async with app.app_context():
            for addr in ['127.0.0.1', '::1', '::ffff:127.0.0.1']:
                assert update._require_local(addr) is None

    async def test_endpoints_use_the_guard(self, isolated, monkeypatch):
        """端点接线断言：_require_local 拒绝时端点原样返回 403。"""
        import quart

        def fake_guard(addr=None):
            return quart.jsonify({'ok': False, 'error': 'forbidden'}), 403

        monkeypatch.setattr(update, '_require_local', fake_guard)
        async with app.test_client() as client:
            resp = await client.get('/api/update/status')
        assert resp.status_code == 403


# ── check ────────────────────────────────────────────────────────────

class TestCheck:
    async def test_dev_mode_supported_false_no_network(self, isolated, dev_mode, monkeypatch):
        def boom():
            raise AssertionError('dev mode must not hit the network')
        monkeypatch.setattr(update, '_make_client', boom)
        async with app.test_client() as client:
            resp = await client.get('/api/update/check')
        data = await resp.get_json()
        assert data['supported'] is False
        assert data['hasUpdate'] is False

    async def test_consume_only_no_network_and_consumes_last_result(self, isolated, frozen, monkeypatch):
        _write_versions(isolated, last_result='ok')

        def boom():
            raise AssertionError('consume_only must not hit the network')
        monkeypatch.setattr(update, '_make_client', boom)

        async with app.test_client() as client:
            resp = await client.get('/api/update/check?consume_only=1')
        data = await resp.get_json()
        assert data['lastResult'] == 'ok'
        assert data['hasUpdate'] is False
        # 一次性消费：文件已置 null
        cfg = json.loads((isolated / 'versions.json').read_text(encoding='utf-8'))
        assert cfg['last_result'] is None

        async with app.test_client() as client:
            resp = await client.get('/api/update/check?consume_only=1')
        assert (await resp.get_json())['lastResult'] is None

    async def test_consume_rolled_back(self, isolated, frozen):
        _write_versions(isolated, last_result='rolled_back')
        async with app.test_client() as client:
            resp = await client.get('/api/update/check?consume_only=1')
        assert (await resp.get_json())['lastResult'] == 'rolled_back'

    async def test_dual_source_takes_larger_version(self, isolated, frozen, monkeypatch):
        src_a = 'http://src-a.test/version.json'
        src_b = 'http://src-b.test/version.json'
        monkeypatch.setattr(update, 'SOURCE_URLS', [src_a, src_b])
        monkeypatch.setattr(update, '_make_client', lambda: FakeAsyncClient(get_map={
            src_a: _version_json(isolated, version='1.1.0'),
            src_b: _version_json(isolated, version='1.9.0'),
        }))
        info = await update._check_latest()
        assert info['latest'] == '1.9.0'  # 取较大者
        assert info['hasUpdate'] is True

    async def test_single_source_failure_does_not_affect(self, isolated, frozen, monkeypatch):
        src_a = 'http://src-a.test/version.json'
        src_b = 'http://src-b.test/version.json'
        monkeypatch.setattr(update, 'SOURCE_URLS', [src_a, src_b])
        fake = FakeAsyncClient(get_map={
            src_a: RuntimeError('network down'),
            src_b: _version_json(isolated, version='1.5.0'),
        })
        monkeypatch.setattr(update, '_make_client', lambda: fake)
        info = await update._check_latest()
        assert info['latest'] == '1.5.0'
        assert info['hasUpdate'] is True

    async def test_all_sources_failed(self, isolated, frozen, monkeypatch):
        src_a = 'http://src-a.test/version.json'
        monkeypatch.setattr(update, 'SOURCE_URLS', [src_a])
        monkeypatch.setattr(update, '_make_client', lambda: FakeAsyncClient(get_map={src_a: RuntimeError('down')}))
        info = await update._check_latest()
        assert info['hasUpdate'] is False
        assert info['error'] == 'update_unavailable'

    async def test_prerelease_source_filtered(self, isolated, frozen, monkeypatch):
        src_a = 'http://src-a.test/version.json'
        monkeypatch.setattr(update, 'SOURCE_URLS', [src_a])
        monkeypatch.setattr(update, '_make_client', lambda: FakeAsyncClient(get_map={
            src_a: _version_json(isolated, version='1.9.0-beta'),
        }))
        info = await update._check_latest()
        assert info['hasUpdate'] is False
        assert info['error'] == 'update_unavailable'

    async def test_missing_win64_assets_no_update(self, isolated, frozen, monkeypatch):
        src_a = 'http://src-a.test/version.json'
        monkeypatch.setattr(update, 'SOURCE_URLS', [src_a])
        monkeypatch.setattr(update, '_make_client', lambda: FakeAsyncClient(get_map={
            src_a: {'version': '1.9.0', 'notes': '', 'assets': {}},
        }))
        info = await update._check_latest()
        assert info['hasUpdate'] is False
        assert info['error'] is None

    async def test_ok_consumption_triggers_cleanup(self, isolated, frozen, monkeypatch):
        _write_versions(isolated, last_result='ok')
        calls = []

        async def fake_cleanup():
            calls.append(1)

        monkeypatch.setattr(update, '_cleanup_old_versions', fake_cleanup)
        monkeypatch.setattr(update, '_make_client', lambda: FakeAsyncClient(get_map={}))
        monkeypatch.setattr(update, 'SOURCE_URLS', [])
        async with app.test_client() as client:
            await client.get('/api/update/check?consume_only=1')
        await asyncio.sleep(0.05)
        assert calls == [1]


# ── 解压防护 ─────────────────────────────────────────────────────────

class TestValidateZip:
    def _make_zip(self, tmp_path, names):
        path = tmp_path / 'x.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for n in names:
                zf.writestr(n, 'data')
        return path

    def test_traversal_rejected(self, tmp_path):
        for name in ['../evil.txt', '/abs.txt', 'C:/abs.txt', 'a/../../evil.txt']:
            zf = zipfile.ZipFile(self._make_zip(tmp_path, [name]))
            with pytest.raises(update.UpdateError, match='traversal'):
                update._validate_zip(zf)

    def test_bundled_state_files_rejected(self, tmp_path):
        for name in [
            '_internal/plugins/.plugin_state.json',
            '_internal/agent_modules/skills/.skill_state.json',
            '_internal/sub/dir/.plugin_state.json',
        ]:
            zf = zipfile.ZipFile(self._make_zip(tmp_path, [name]))
            with pytest.raises(update.UpdateError, match='state file'):
                update._validate_zip(zf)

    def test_entry_count_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(update, '_MAX_ENTRIES', 3)
        zf = zipfile.ZipFile(self._make_zip(tmp_path, [f'f{i}' for i in range(4)]))
        with pytest.raises(update.UpdateError, match='entries'):
            update._validate_zip(zf)

    def test_total_size_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(update, '_MAX_TOTAL_SIZE', 10)
        path = tmp_path / 'big.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('big.bin', 'x' * 100)
        zf = zipfile.ZipFile(path)
        with pytest.raises(update.UpdateError, match='1GB'):
            update._validate_zip(zf)

    def test_unknown_plugin_dir_rejected(self, tmp_path, monkeypatch):
        resource_root = tmp_path / 'res'
        (resource_root / 'plugins' / 'known_plugin').mkdir(parents=True)
        monkeypatch.setattr(update, 'get_resource_root', lambda: str(resource_root))

        ok = zipfile.ZipFile(self._make_zip(tmp_path, ['_internal/plugins/known_plugin/x.txt']))
        update._validate_zip(ok)  # 已知插件目录放行

        bad = zipfile.ZipFile(self._make_zip(tmp_path, ['_internal/plugins/evil_plugin/x.txt']))
        with pytest.raises(update.UpdateError, match='unknown plugin'):
            update._validate_zip(bad)


# ── download ─────────────────────────────────────────────────────────

class TestDownload:
    def _make_package_zip(self, tmp_path):
        path = tmp_path / 'pkg.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('ZaoWu.exe', 'fake exe')
            zf.writestr('_internal/app/data.txt', 'hello')
        return path

    def _sha256(self, path):
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            h.update(f.read())
        return h.hexdigest()

    async def test_full_flow_with_fallback_and_recheck(self, isolated, frozen, monkeypatch):
        pkg = self._make_package_zip(isolated)
        src = 'http://src.test/version.json'
        url_a, url_b = 'http://a.test/pkg.zip', 'http://b.test/pkg.zip'
        vj = _version_json(isolated, version='1.3.0', urls=[url_a, url_b],
                           sha256=self._sha256(pkg), size=pkg.stat().st_size)
        fake = FakeAsyncClient(
            get_map={src: vj},
            streams={url_a: RuntimeError('first source down'), url_b: [pkg.read_bytes()]},
        )
        monkeypatch.setattr(update, 'SOURCE_URLS', [src])
        monkeypatch.setattr(update, '_make_client', lambda: fake)

        async with app.test_client() as client:
            resp = await client.get('/api/update/download')
        assert resp.status_code == 200
        assert (await resp.get_json())['ok'] is True

        # 重新检查（不信任前端参数）：下载期间再次请求了 version.json
        assert src in fake.get_calls
        # 解压落位：目录名取自远端 version 字段
        assert (isolated / 'versions' / '1.3.0' / '_internal' / 'app' / 'data.txt').exists()
        assert update._status['state'] == 'ready'

    async def test_checksum_mismatch(self, isolated, frozen, monkeypatch):
        pkg = self._make_package_zip(isolated)
        src = 'http://src.test/version.json'
        url_a = 'http://a.test/pkg.zip'
        vj = _version_json(isolated, version='1.3.0', urls=[url_a], sha256='0' * 64, size=10)
        fake = FakeAsyncClient(get_map={src: vj}, streams={url_a: [pkg.read_bytes()]})
        monkeypatch.setattr(update, 'SOURCE_URLS', [src])
        monkeypatch.setattr(update, '_make_client', lambda: fake)
        async with app.test_client() as client:
            resp = await client.get('/api/update/download')
        assert resp.status_code == 400
        assert (await resp.get_json())['error'] == 'checksum mismatch'

    async def test_missing_sha256_rejected(self, isolated, frozen, monkeypatch):
        pkg = self._make_package_zip(isolated)
        src = 'http://src.test/version.json'
        vj = _version_json(isolated, version='1.3.0', urls=['http://a.test/pkg.zip'])
        vj['assets']['win64'].pop('sha256')
        fake = FakeAsyncClient(get_map={src: vj}, streams={'http://a.test/pkg.zip': [pkg.read_bytes()]})
        monkeypatch.setattr(update, 'SOURCE_URLS', [src])
        monkeypatch.setattr(update, '_make_client', lambda: fake)
        async with app.test_client() as client:
            resp = await client.get('/api/update/download')
        assert resp.status_code == 400
        assert (await resp.get_json())['error'] == 'incomplete asset metadata'

    async def test_all_download_sources_fail(self, isolated, frozen, monkeypatch):
        pkg = self._make_package_zip(isolated)
        src = 'http://src.test/version.json'
        url_a, url_b = 'http://a.test/pkg.zip', 'http://b.test/pkg.zip'
        vj = _version_json(isolated, version='1.3.0', urls=[url_a, url_b],
                           sha256=self._sha256(pkg), size=10)
        fake = FakeAsyncClient(
            get_map={src: vj},
            streams={url_a: RuntimeError('down'), url_b: RuntimeError('down too')},
        )
        monkeypatch.setattr(update, 'SOURCE_URLS', [src])
        monkeypatch.setattr(update, '_make_client', lambda: fake)
        async with app.test_client() as client:
            resp = await client.get('/api/update/download')
        assert resp.status_code == 400
        assert 'all download sources failed' in (await resp.get_json())['error']

    async def test_concurrent_download_rejected(self, isolated, frozen, monkeypatch):
        # 互斥锁：手动占用后第二次请求 409 快速失败
        await update._download_lock.acquire()
        try:
            async with app.test_client() as client:
                resp = await client.get('/api/update/download')
            assert resp.status_code == 409
            assert (await resp.get_json())['error'] == 'download_in_progress'
        finally:
            update._download_lock.release()

    async def test_dev_mode_download_rejected(self, isolated, dev_mode):
        async with app.test_client() as client:
            resp = await client.get('/api/update/download')
        assert resp.status_code == 400
        assert (await resp.get_json())['error'] == 'unsupported'

    async def test_staging_cleanup_aborts_on_failure(self, isolated, frozen, monkeypatch):
        """清理失败（文件占用模拟）→ 中止下载返回错误，防残留合并。"""
        src = 'http://src.test/version.json'
        vj = _version_json(isolated, version='1.3.0', urls=['http://a.test/pkg.zip'],
                           sha256='0' * 64, size=10)
        monkeypatch.setattr(update, 'SOURCE_URLS', [src])
        monkeypatch.setattr(update, '_make_client', lambda: FakeAsyncClient(get_map={src: vj}))
        (isolated / 'versions' / '.staging').mkdir(parents=True)

        def boom(path):
            raise OSError('in use')
        monkeypatch.setattr(update.shutil, 'rmtree', boom)
        async with app.test_client() as client:
            resp = await client.get('/api/update/download')
        assert resp.status_code == 500


# ── apply ────────────────────────────────────────────────────────────

class FakeEvent:
    def __init__(self):
        self.set_called = False

    def set(self):
        self.set_called = True


class TestApply:
    async def test_apply_success_writes_pending_spawns_and_sets_event(
        self, isolated, frozen, monkeypatch
    ):
        import server_quart
        _write_versions(isolated, current='v1.1.0')
        update._status.update({'state': 'ready', 'version': '1.3.0'})
        (isolated / 'versions' / '1.3.0').mkdir(parents=True)
        (isolated / update.LAUNCHER_NAME).write_text('fake launcher')

        popen_calls = []

        class FakePopen:
            def __init__(self, args, cwd=None, close_fds=None):
                popen_calls.append((args, cwd))

        monkeypatch.setattr(update.subprocess, 'Popen', FakePopen)
        fake_event = FakeEvent()
        monkeypatch.setattr(server_quart, '_shutdown_event', fake_event)

        async with app.test_client() as client:
            resp = await client.post('/api/update/apply')
        assert resp.status_code == 200
        assert (await resp.get_json())['ok'] is True

        cfg = json.loads((isolated / 'versions.json').read_text(encoding='utf-8'))
        assert cfg['pending'] == '1.3.0'
        assert popen_calls[0][0][:2] == [str(isolated / update.LAUNCHER_NAME), '--switch']
        assert popen_calls[0][0][3] == str(os.getpid())
        assert fake_event.set_called is True  # 事件 set 后仍返回 ok

    async def test_apply_idempotent_when_pending_exists(self, isolated, frozen, monkeypatch):
        _write_versions(isolated, pending='1.3.0')
        update._status.update({'state': 'ready', 'version': '1.3.0'})
        monkeypatch.setattr(update.subprocess, 'Popen', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('must not spawn')))
        async with app.test_client() as client:
            resp = await client.post('/api/update/apply')
        assert (await resp.get_json())['ok'] is True

    async def test_apply_not_ready_rejected(self, isolated, frozen):
        _write_versions(isolated)
        async with app.test_client() as client:
            resp = await client.post('/api/update/apply')
        assert resp.status_code == 400
        assert (await resp.get_json())['error'] == 'not_ready'

    async def test_apply_dev_mode_rejected(self, isolated, dev_mode):
        async with app.test_client() as client:
            resp = await client.post('/api/update/apply')
        assert resp.status_code == 400


# ── status ───────────────────────────────────────────────────────────

class TestStatus:
    async def test_status_snapshot(self, isolated, monkeypatch):
        monkeypatch.setattr(update, '_status', {'state': 'ready', 'progress': 100, 'version': '1.3.0', 'error': None})
        async with app.test_client() as client:
            resp = await client.get('/api/update/status')
        data = await resp.get_json()
        assert data['state'] == 'ready'
        assert data['version'] == '1.3.0'
