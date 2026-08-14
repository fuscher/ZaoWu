"""一次性用户数据迁移（services/userdata_migration.py）测试。"""

import json
import os
import shutil
import sys

import pytest

import services.userdata_migration as migration
from services.versions_config import read_versions_config, versions_path, write_versions_config


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


class TestVersionsConfig:
    def test_write_read_roundtrip(self, tmp_path):
        data = {'schema': 1, 'current': 'v1.2.0', 'last_good': 'v1.1.0', 'pending': None, 'last_result': None}
        write_versions_config(data, str(tmp_path))
        assert (tmp_path / 'versions.json').exists()
        assert not (tmp_path / 'versions.json.tmp').exists()  # 原子写无残留
        assert read_versions_config(str(tmp_path)) == data

    def test_read_missing_returns_empty(self, tmp_path):
        assert read_versions_config(str(tmp_path)) == {}

    def test_read_corrupt_returns_empty(self, tmp_path):
        (tmp_path / 'versions.json').write_text('{broken', encoding='utf-8')
        assert read_versions_config(str(tmp_path)) == {}

    def test_versions_path_defaults_to_project_root(self):
        from zaowu_paths import get_project_root

        assert versions_path() == os.path.join(get_project_root(), 'versions.json')
