"""services/versions_config.py 读写与职责分离测试。"""

import os

from services.versions_config import (
    read_versions_config,
    versions_path,
    write_versions_config,
)


class TestReadWrite:
    def test_write_read_roundtrip(self, tmp_path):
        data = {'schema': 1, 'current': 'v1.2.0', 'last_good': 'v1.1.0',
                'pending': None, 'last_result': None}
        write_versions_config(data, str(tmp_path))
        assert (tmp_path / 'versions.json').exists()
        assert not (tmp_path / 'versions.json.tmp').exists()
        assert read_versions_config(str(tmp_path)) == data

    def test_write_is_atomic_and_overwrites(self, tmp_path):
        write_versions_config({'current': 'v1'}, str(tmp_path))
        write_versions_config({'current': 'v2'}, str(tmp_path))
        assert read_versions_config(str(tmp_path))['current'] == 'v2'
        assert not (tmp_path / 'versions.json.tmp').exists()

    def test_read_missing_returns_empty(self, tmp_path):
        assert read_versions_config(str(tmp_path)) == {}

    def test_read_corrupt_returns_empty(self, tmp_path):
        (tmp_path / 'versions.json').write_text('{broken', encoding='utf-8')
        assert read_versions_config(str(tmp_path)) == {}

    def test_read_non_dict_returns_empty(self, tmp_path):
        (tmp_path / 'versions.json').write_text('[1,2,3]', encoding='utf-8')
        assert read_versions_config(str(tmp_path)) == {}

    def test_versions_path_defaults_to_project_root(self):
        from zaowu_paths import get_project_root

        assert versions_path() == os.path.join(get_project_root(), 'versions.json')


class TestResponsibilitySeparation:
    """写入职责分离是双方代码注释中的硬性约束（应用只写 pending；
    启动器只写 current/last_good/last_result/pending→null）。
    用源码断言把注释和实现绑在一起，防止无声破坏格式。"""

    def test_python_module_docstring_declares_duties(self):
        import services.versions_config as vc
        doc = vc.__doc__ or ''
        assert '应用只写' in doc and '启动器只写' in doc

    def test_launcher_side_declares_duties(self, tmp_path):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_go = os.path.join(repo_root, 'launcher', 'config.go')
        with open(cfg_go, encoding='utf-8') as f:
            src = f.read()
        assert '启动器只写' in src and '应用只写' in src
