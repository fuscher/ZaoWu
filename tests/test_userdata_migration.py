"""一次性用户数据迁移（services/userdata_migration.py）测试。"""

import json
import os
import shutil
import sys

import pytest

import services.userdata_migration as migration


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def _mk_skill(src, name):
    d = os.path.join(src, 'agent_modules', 'skills', name)
    _write(os.path.join(d, 'manifest.json'), {'name': name, 'type': 'skill'})
    _write(os.path.join(d, '__init__.py'), {})
    return d


def _build_source(tmp_path):
    """构造迁移源：插件状态 + 技能状态 + 用户导入/内置技能混合。"""
    src = tmp_path / 'src_internal'
    _write(src / 'plugins' / '.plugin_state.json', {'version': 1, 'plugins': {'a': {'enabled': True}}})
    _write(
        src / 'agent_modules' / 'skills' / '.skill_state.json',
        {'version': 1, 'enabled': ['myskill'], 'disabled': ['offskill'], 'deleted': ['del_skill']},
    )
    _mk_skill(src, 'myskill')
    _mk_skill(src, 'offskill')
    _mk_skill(src, 'del_skill')      # deleted → 不复制目录
    _mk_skill(src, 'builtin_skill')  # 未入状态名单的内置技能 → 不复制
    return str(src)


def _mk_version(root, version):
    """在 root/versions/<version>/_internal 建目录，返回 internal 路径。"""
    internal = os.path.join(str(root), 'versions', version, '_internal')
    os.makedirs(internal, exist_ok=True)
    return internal


def _mk_plugin(plugins_dir, name, *, disabled=False, builtin=False, marker=None):
    """在 plugins_dir 下创建插件目录（或 .disabled 卸载态）。

    写入 manifest.json（含可选 builtin 标记）+ __init__.py，可选 marker.txt
    用于断言「同名取新」复制的是哪一版本副本。
    """
    dname = name + '.disabled' if disabled else name
    d = os.path.join(plugins_dir, dname)
    os.makedirs(d, exist_ok=True)
    manifest = {'name': name, 'version': '1.0.0', 'minApiVersion': '1.0.0'}
    if builtin:
        manifest['builtin'] = True
    with open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f)
    with open(os.path.join(d, '__init__.py'), 'w', encoding='utf-8') as f:
        f.write('def zaowu_register_routes():\n    return []\n')
    if marker is not None:
        with open(os.path.join(d, 'marker.txt'), 'w', encoding='utf-8') as f:
            f.write(marker)
    return d


class TestMigrationSource:
    def test_frozen_prefers_last_good(self, tmp_path, monkeypatch):
        monkeypatch.setattr(migration.sys, 'frozen', True, raising=False)
        root = tmp_path
        (tmp_path / 'versions' / 'v1.1.0' / '_internal').mkdir(parents=True)
        (tmp_path / 'versions' / 'v1.2.0' / '_internal').mkdir(parents=True)
        _write(
            tmp_path / 'versions.json',
            {'schema': 1, 'current': 'v1.2.0', 'last_good': 'v1.1.0', 'pending': None, 'last_result': None},
        )
        assert migration.migration_source(str(root)) == str(
            tmp_path / 'versions' / 'v1.1.0' / '_internal'
        )

    def test_frozen_falls_back_to_current(self, tmp_path, monkeypatch):
        monkeypatch.setattr(migration.sys, 'frozen', True, raising=False)
        (tmp_path / 'versions' / 'v1.2.0' / '_internal').mkdir(parents=True)
        _write(
            tmp_path / 'versions.json',
            {'schema': 1, 'current': 'v1.2.0', 'last_good': None, 'pending': None, 'last_result': None},
        )
        # last_good 为空 → 源为 current
        assert migration.migration_source(str(tmp_path)) == str(
            tmp_path / 'versions' / 'v1.2.0' / '_internal'
        )

    def test_frozen_missing_or_corrupt_config_uses_resource_root(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(migration.sys, 'frozen', True, raising=False)
        monkeypatch.setattr(migration, 'get_resource_root', lambda: str(tmp_path / 'res'))
        # 无 versions.json
        assert migration.migration_source(str(tmp_path)) == str(tmp_path / 'res')
        # 损坏的 versions.json
        (tmp_path / 'versions.json').write_text('{broken', encoding='utf-8')
        assert migration.migration_source(str(tmp_path)) == str(tmp_path / 'res')

    def test_dev_mode_uses_resource_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(migration.sys, 'frozen', False, raising=False)
        monkeypatch.setattr(migration, 'get_resource_root', lambda: str(tmp_path / 'res'))
        assert migration.migration_source(str(tmp_path)) == str(tmp_path / 'res')


class TestMigrateUserdata:
    def test_full_migration(self, tmp_path):
        src = _build_source(tmp_path)
        root = str(tmp_path / 'root')
        assert migration.migrate_userdata(root, src) is True

        # 插件状态复制且内容一致
        assert json.loads((tmp_path / 'root' / '.plugin_state.json').read_text(encoding='utf-8')) == {
            'version': 1,
            'plugins': {'a': {'enabled': True}},
        }
        # 技能状态复制且内容一致
        assert json.loads(
            (tmp_path / 'root' / 'skills' / '.skill_state.json').read_text(encoding='utf-8')
        )['enabled'] == ['myskill']
        # enabled/disabled 名单内的技能目录被复制，deleted 与内置技能不复制
        assert (tmp_path / 'root' / 'skills' / 'myskill').is_dir()
        assert (tmp_path / 'root' / 'skills' / 'offskill').is_dir()
        assert not (tmp_path / 'root' / 'skills' / 'del_skill').exists()
        assert not (tmp_path / 'root' / 'skills' / 'builtin_skill').exists()
        # 迁移标记已写
        assert migration.has_migration_marker(root)

    def test_fill_missing_only_does_not_overwrite(self, tmp_path):
        src = _build_source(tmp_path)
        root = tmp_path / 'root'
        (root / 'skills' / 'myskill').mkdir(parents=True)
        sentinel = root / 'skills' / 'myskill' / 'sentinel.txt'
        sentinel.write_text('keep me', encoding='utf-8')
        (root / '.plugin_state.json').write_text('{"sentinel": true}', encoding='utf-8')

        assert migration.migrate_userdata(str(root), src) is True
        # 已存在的目标不被覆盖（仅补缺）
        assert sentinel.read_text(encoding='utf-8') == 'keep me'
        assert json.loads((root / '.plugin_state.json').read_text(encoding='utf-8')) == {
            'sentinel': True
        }

    def test_copy_failure_returns_false_without_marker(self, tmp_path, monkeypatch):
        src = _build_source(tmp_path)
        root = str(tmp_path / 'root')

        def boom(*a, **kw):
            raise OSError('disk full')

        monkeypatch.setattr(migration.shutil, 'copy2', boom)
        assert migration.migrate_userdata(root, src) is False
        assert not migration.has_migration_marker(root)

    def test_run_if_needed_skips_when_marked(self, tmp_path, monkeypatch):
        root = str(tmp_path / 'root')
        os.makedirs(root)
        _write(tmp_path / 'root' / migration.MIGRATION_MARKER, {'migrated_at': 'x'})
        monkeypatch.setattr(migration, 'migrate_userdata', lambda *a, **kw: pytest.fail('should not run'))
        migration.run_migration_if_needed(root)

    def test_run_if_needed_tolerates_exceptions(self, tmp_path, monkeypatch):
        root = str(tmp_path / 'root')
        os.makedirs(root)

        def boom(*a, **kw):
            raise RuntimeError('unexpected')

        monkeypatch.setattr(migration, 'migration_source', boom)
        # 钩子级不抛出
        migration.run_migration_if_needed(root)


class TestPathRedirection:
    def test_plugin_state_path_redirected(self, tmp_path):
        from plugin_system.manager import PluginManager

        state_dir = str(tmp_path)
        mgr = PluginManager(str(tmp_path / 'plugins'), state_dir=state_dir)
        assert mgr._state_path == os.path.join(state_dir, '.plugin_state.json')

    def test_plugin_state_path_defaults_to_plugins_dir(self, tmp_path):
        from plugin_system.manager import PluginManager

        plugins_dir = str(tmp_path / 'plugins')
        mgr = PluginManager(plugins_dir)
        assert mgr._state_path == os.path.join(plugins_dir, '.plugin_state.json')

    def test_user_skills_dir_is_at_project_root(self):
        from services.skill_loader import USER_SKILLS_DIR
        from zaowu_paths import get_project_root

        assert USER_SKILLS_DIR == os.path.join(get_project_root(), 'skills')


# ── 每启动插件救援（rescue_user_plugins）──────────────────────────────


@pytest.fixture
def rescue_root(tmp_path, monkeypatch):
    """隔离救援的 get_resource_root 回退，避免误扫真实仓库 plugins。"""
    res = tmp_path / 'res_root'
    res.mkdir()
    monkeypatch.setattr(migration, 'get_resource_root', lambda: str(res))
    return tmp_path, res


class TestRescueUserPlugins:
    def test_runs_even_when_marker_present(self, rescue_root):
        """回归：老部署迁移标记已存在时，救援仍执行（不受标记守卫拦截）。"""
        root, res = rescue_root
        internal = _mk_version(root, 'v1.1.0')
        _mk_plugin(os.path.join(internal, 'plugins'), 'sim_user_plugin')
        _write(os.path.join(str(root), migration.MIGRATION_MARKER), {'migrated_at': 'x'})
        assert migration.rescue_user_plugins(str(root)) == 1
        assert os.path.isdir(os.path.join(str(root), 'plugins', 'sim_user_plugin'))

    def test_copies_and_is_idempotent(self, rescue_root):
        """用户插件复制到部署根；二次调用目标已存在 → 复制 0（幂等）。"""
        root, res = rescue_root
        internal = _mk_version(root, 'v1.1.0')
        _mk_plugin(os.path.join(internal, 'plugins'), 'sim_user_plugin')
        assert migration.rescue_user_plugins(str(root)) == 1
        assert os.path.isdir(os.path.join(str(root), 'plugins', 'sim_user_plugin'))
        assert migration.rescue_user_plugins(str(root)) == 0

    def test_scans_all_versions_skips_staging_and_dotdirs(self, rescue_root):
        """隔版本安装（插件只在更早的 v1.0.0）仍被全目录扫描救出；
        扫描跳过 .staging 与点前缀目录。"""
        root, res = rescue_root
        internal_old = _mk_version(root, 'v1.0.0')  # 更早版本（非 last_good）
        _mk_plugin(os.path.join(internal_old, 'plugins'), 'sim_user_plugin')
        _mk_version(root, 'v1.1.0')  # last_good，无插件
        _mk_version(root, 'v1.2.0')  # current，无插件
        os.makedirs(os.path.join(str(root), 'versions', '.staging', '_internal', 'plugins', 'noise'))
        os.makedirs(os.path.join(str(root), 'versions', '.hidden', '_internal'))
        assert migration.rescue_user_plugins(str(root)) == 1
        assert os.path.isdir(os.path.join(str(root), 'plugins', 'sim_user_plugin'))
        assert not os.path.isdir(os.path.join(str(root), 'plugins', 'noise'))

    def test_prefers_newest_when_duplicate_enabled(self, rescue_root):
        """同名取新：两版本均启用时以版本号大的副本为准。"""
        root, res = rescue_root
        _mk_plugin(os.path.join(_mk_version(root, 'v1.0.0'), 'plugins'), 'P', marker='old')
        _mk_plugin(os.path.join(_mk_version(root, 'v1.1.0'), 'plugins'), 'P', marker='new')
        migration.rescue_user_plugins(str(root))
        marker = open(os.path.join(str(root), 'plugins', 'P', 'marker.txt'), encoding='utf-8').read()
        assert marker == 'new'

    def test_authority_low_enabled_high_disabled(self, rescue_root):
        """权威状态回归：低版本启用 + 高版本 P.disabled → 不救出（跨版本复活被阻断）。"""
        root, res = rescue_root
        _mk_plugin(os.path.join(_mk_version(root, 'v1.0.0'), 'plugins'), 'P')
        _mk_plugin(os.path.join(_mk_version(root, 'v1.1.0'), 'plugins'), 'P', disabled=True)
        assert migration.rescue_user_plugins(str(root)) == 0
        assert not os.path.isdir(os.path.join(str(root), 'plugins', 'P'))

    def test_authority_low_disabled_high_enabled(self, rescue_root):
        """反向：低版本 P.disabled + 高版本启用 → 救出高版本副本（不做全局黑名单）。"""
        root, res = rescue_root
        _mk_plugin(os.path.join(_mk_version(root, 'v1.0.0'), 'plugins'), 'P', disabled=True)
        _mk_plugin(os.path.join(_mk_version(root, 'v1.1.0'), 'plugins'), 'P')
        assert migration.rescue_user_plugins(str(root)) == 1
        assert os.path.isdir(os.path.join(str(root), 'plugins', 'P'))

    def test_source_disabled_dot_n_normalized(self, rescue_root):
        """源侧 P.disabled.1（多次卸载重名递增）归一为基名 P 的卸载态，
        不救出、也不当作独立插件名。"""
        root, res = rescue_root
        base = os.path.join(_mk_version(root, 'v1.1.0'), 'plugins')
        _mk_plugin(base, 'P', disabled=True)
        os.rename(os.path.join(base, 'P.disabled'), os.path.join(base, 'P.disabled.1'))
        assert migration.rescue_user_plugins(str(root)) == 0
        assert not os.path.isdir(os.path.join(str(root), 'plugins', 'P'))
        assert not os.path.isdir(os.path.join(str(root), 'plugins', 'P.disabled.1'))

    def test_root_uninstalled_state_blocks(self, rescue_root):
        """部署根卸载态（P.disabled.1）优先级最高：任何旧版本启用副本都不救出。"""
        root, res = rescue_root
        _mk_plugin(os.path.join(_mk_version(root, 'v1.1.0'), 'plugins'), 'P')
        dest = os.path.join(str(root), 'plugins')
        os.makedirs(dest)
        os.makedirs(os.path.join(dest, 'P.disabled.1'))
        assert migration.rescue_user_plugins(str(root)) == 0
        assert not os.path.isdir(os.path.join(dest, 'P'))

    def test_same_dir_P_and_P_disabled_P_wins(self, rescue_root):
        """同一目录内 P 与 P.disabled 并存：目录名排序保证 P 先登记 → 视为启用。"""
        root, res = rescue_root
        base = os.path.join(_mk_version(root, 'v1.1.0'), 'plugins')
        _mk_plugin(base, 'P')
        _mk_plugin(base, 'P', disabled=True)
        assert migration.rescue_user_plugins(str(root)) == 1
        assert os.path.isdir(os.path.join(str(root), 'plugins', 'P'))

    def test_skips_builtin_by_manifest_flag(self, rescue_root):
        """manifest builtin:true（名字不在当前内置清单，模拟被删除的内置）→ 跳过。"""
        root, res = rescue_root
        _mk_plugin(os.path.join(_mk_version(root, 'v1.1.0'), 'plugins'),
                   'sim_builtin_plugin', builtin=True)
        assert migration.rescue_user_plugins(str(root)) == 0
        assert not os.path.isdir(os.path.join(str(root), 'plugins', 'sim_builtin_plugin'))

    def test_skips_builtin_by_name_fallback(self, rescue_root):
        """名字在当前版本内置清单中（无 builtin 标记）的目录 → 跳过（兜底信号）。"""
        root, res = rescue_root
        os.makedirs(os.path.join(str(res), 'plugins', 'old_builtin'))
        _mk_plugin(os.path.join(_mk_version(root, 'v1.1.0'), 'plugins'), 'old_builtin')
        assert migration.rescue_user_plugins(str(root)) == 0

    def test_skips_dot_underscore_and_missing_init(self, rescue_root):
        """'.'/'_' 开头目录跳过；仅有 manifest.json 无 __init__.py → 候选不齐不救出。"""
        root, res = rescue_root
        base = os.path.join(_mk_version(root, 'v1.1.0'), 'plugins')
        os.makedirs(os.path.join(base, '.hidden_plugin'))
        os.makedirs(os.path.join(base, '_under_plugin'))
        d = os.path.join(base, 'broken_no_init')
        os.makedirs(d)
        with open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8') as f:
            json.dump({'name': 'broken_no_init', 'version': '1.0.0'}, f)
        assert migration.rescue_user_plugins(str(root)) == 0

    def test_no_source_plugins_no_error_and_dest_autocreated(self, rescue_root):
        """迁移源无 plugins/ 目录时不报错；有插件时目标 root/plugins/ 自动创建。"""
        root, res = rescue_root
        _mk_version(root, 'v1.1.0')  # 无 plugins 子目录
        assert migration.rescue_user_plugins(str(root)) == 0
        _mk_plugin(os.path.join(_mk_version(root, 'v1.2.0'), 'plugins'), 'P2')
        assert migration.rescue_user_plugins(str(root)) == 1
        assert os.path.isdir(os.path.join(str(root), 'plugins', 'P2'))
