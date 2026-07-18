"""Tests for the code_assistant_utils plugin.

验证插件 manifest、agent 工具注册、各工具函数行为，
以及通过 PluginManager 加载后的兼容性。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid as uuid_module
from pathlib import Path

import pytest

from plugin_system.manager import PluginManager
from services.tool_registry import ToolDefinition

# Import plugin under test.  It must not fail when imported outside the
# plugin_api context because helper functions fall back to defaults.
import plugins.code_assistant_utils as plugin_module


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def plugin_tools():
    """Return the ToolDefinition list registered by the plugin."""
    return plugin_module.zaowu_register_agent_tools()


@pytest.fixture
def temp_project():
    """Create a temporary directory with a few source files for LOC tests."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'main.py').write_text(
            '# main entry\nimport os\n\ndef run():\n    pass\n',
            encoding='utf-8',
        )
        (root / 'README.md').write_text('# Project\n\nA sample project.\n', encoding='utf-8')
        (root / 'node_modules').mkdir()
        (root / 'node_modules' / 'fake.js').write_text('// ignored\n', encoding='utf-8')
        yield str(root)


# ── Manifest & tool registration tests ──────────────────────────────

def test_manifest_exists():
    """The plugin directory must contain a valid manifest.json."""
    plugin_dir = Path(__file__).parent.parent / 'plugins' / 'code_assistant_utils'
    manifest_path = plugin_dir / 'manifest.json'
    assert manifest_path.exists(), 'manifest.json is required'
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert data['name'] == 'code_assistant_utils'
    assert data['version'] == '1.0.0'
    assert data.get('enabled') is True
    assert 'config' in data


def test_register_agent_tools_returns_tool_definitions(plugin_tools):
    """zaowu_register_agent_tools must return a list of ToolDefinition."""
    assert isinstance(plugin_tools, list)
    assert len(plugin_tools) == 4
    for tool in plugin_tools:
        assert isinstance(tool, ToolDefinition)
        assert tool.name
        assert tool.description
        assert isinstance(tool.parameters, dict)
        assert tool.parameters.get('type') == 'object'
        assert callable(tool.handler)
        assert isinstance(tool.tags, list)


def test_tool_names_are_unique(plugin_tools):
    """Tool names must be unique within the plugin."""
    names = [t.name for t in plugin_tools]
    assert len(names) == len(set(names))


def test_tools_do_not_require_approval(plugin_tools):
    """All tools in this plugin are read-only and should not require approval."""
    for tool in plugin_tools:
        assert tool.requires_approval is False, f'{tool.name} should not require approval'


# ── get_current_time tests ──────────────────────────────────────────

def test_get_current_time_local():
    result = plugin_module.get_current_time('local')
    assert result['ok'] is True
    assert 'iso' in result
    assert 'date' in result
    assert 'time' in result
    assert 'timestamp' in result
    assert result['timezone'] not in ('UTC', '')


def test_get_current_time_utc():
    result = plugin_module.get_current_time('utc')
    assert result['ok'] is True
    assert result['timezone'] == 'UTC'
    assert result['timestamp'] > 0


# ── count_code_lines tests ──────────────────────────────────────────

def test_count_code_lines_for_directory(temp_project):
    result = plugin_module.count_code_lines(temp_project)
    assert result['ok'] is True
    assert result['files'] == 2  # main.py + README.md
    assert result['total_lines'] == 8
    assert result['code_lines'] >= 3
    assert result['comment_lines'] >= 2


def test_count_code_lines_for_file(temp_project):
    file_path = os.path.join(temp_project, 'main.py')
    result = plugin_module.count_code_lines(file_path)
    assert result['ok'] is True
    assert result['files'] == 1
    assert result['total_lines'] == 5


def test_count_code_lines_excludes_binary(temp_project):
    binary_file = os.path.join(temp_project, 'binary.dat')
    Path(binary_file).write_bytes(b'\x00\x01\x02\x03')
    result = plugin_module.count_code_lines(temp_project)
    assert result['ok'] is True
    assert result['files'] == 2  # binary.dat ignored


def test_count_code_lines_missing_path():
    result = plugin_module.count_code_lines('/non/existent/path')
    assert result['ok'] is False
    assert 'does not exist' in result['error']


# ── generate_uuid tests ─────────────────────────────────────────────

def test_generate_uuid_single():
    result = plugin_module.generate_uuid(1)
    assert result['ok'] is True
    assert result['count'] == 1
    assert len(result['uuids']) == 1
    uuid_module.UUID(result['uuids'][0], version=4)


def test_generate_uuid_multiple():
    result = plugin_module.generate_uuid(3)
    assert result['ok'] is True
    assert result['count'] == 3
    assert len(set(result['uuids'])) == 3


def test_generate_uuid_clamps_out_of_range():
    assert plugin_module.generate_uuid(0)['count'] == 1
    assert plugin_module.generate_uuid(100)['count'] == 10


def test_generate_uuid_invalid_input():
    result = plugin_module.generate_uuid('abc')
    assert result['ok'] is False


# ── format_json tests ───────────────────────────────────────────────

def test_format_json_valid():
    raw = '{"a":1,"b":[2,3]}'
    result = plugin_module.format_json(raw, indent=2)
    assert result['ok'] is True
    assert result['is_valid'] is True
    assert json.loads(result['formatted']) == {'a': 1, 'b': [2, 3]}


def test_format_json_invalid():
    result = plugin_module.format_json('{invalid json}', indent=2)
    assert result['ok'] is False
    assert result['is_valid'] is False
    assert 'invalid JSON' in result['error']


# ── PluginManager integration / compatibility tests ─────────────────

def test_plugin_loads_and_registers_tools():
    """Verify the plugin can be discovered, loaded and its tools collected."""
    import asyncio

    plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'plugins')
    mgr = PluginManager(plugins_dir)
    loaded, broken = asyncio.run(mgr.load_all())

    plugin_names = {p['name'] for p in mgr.list_plugins()}
    assert 'code_assistant_utils' in plugin_names, 'plugin should be loaded'
    assert not mgr.get_plugin('code_assistant_utils')['error']

    # The plugin may be disabled by persisted state; enable it explicitly
    # so the test does not depend on mutable .plugin_state.json.
    asyncio.run(mgr.enable('code_assistant_utils', persist=False))

    tools = asyncio.run(mgr.collect_agent_tools())
    plugin_tool_names = [
        t.name for t in tools
        if getattr(t, 'name', '').startswith(('get_current_time', 'count_code_lines', 'generate_uuid', 'format_json'))
    ]
    assert 'get_current_time' in plugin_tool_names
    assert 'count_code_lines' in plugin_tool_names
    assert 'generate_uuid' in plugin_tool_names
    assert 'format_json' in plugin_tool_names


def test_plugin_imports_without_plugin_api_context():
    """The plugin module must be importable in test contexts without plugin_api."""
    # Re-import is safe because the module is already loaded; this mainly verifies
    # that top-level code does not eagerly access plugin_api.
    assert callable(plugin_module.get_current_time)
    assert callable(plugin_module.count_code_lines)
    assert callable(plugin_module.generate_uuid)
    assert callable(plugin_module.format_json)


# ── Route registration on enable tests ──────────────────────────────

@pytest.fixture
def disabled_code_assistant_plugins_dir(tmp_path):
    """Return a temp plugins dir with code_assistant_utils disabled at startup."""
    src = Path(__file__).parent.parent / 'plugins' / 'code_assistant_utils'
    dst = tmp_path / 'code_assistant_utils'
    shutil.copytree(src, dst)
    state = {
        'version': 1,
        'plugins': {
            'code_assistant_utils': {
                'enabled': False,
                'config': {},
            },
        },
    }
    (tmp_path / '.plugin_state.json').write_text(
        json.dumps(state, ensure_ascii=False), encoding='utf-8',
    )
    return str(tmp_path)


def test_routes_registered_when_enabled_after_startup(disabled_code_assistant_plugins_dir):
    """Plugins disabled at startup must register routes when later enabled.

    This regression test covers the case where the README viewer returns an
    HTML SPA fallback (``<!DOCTYPE...``) because the plugin blueprint was
    never registered.
    """
    import asyncio

    from quart import Quart
    from plugin_system.api import plugin_api

    async def _run():
        app = Quart(__name__)
        mgr = PluginManager(disabled_code_assistant_plugins_dir)
        mgr.attach_app(app)

        loaded, broken = await mgr.load_all()
        assert loaded == 1
        assert broken == 0

        record = mgr._records.get('code_assistant_utils')
        assert record is not None
        assert record.enabled is False
        assert record._routes_registered is False

        await mgr.enable('code_assistant_utils', persist=False)

        assert record.enabled is True
        assert record._routes_registered is True
        registered = plugin_api.registered_blueprints()
        assert any(
            b.get('plugin') == 'code_assistant_utils'
            and b.get('blueprint') == 'code_assistant_utils'
            for b in registered
        ), f'expected code_assistant_utils blueprint, got {registered}'

    asyncio.run(_run())
