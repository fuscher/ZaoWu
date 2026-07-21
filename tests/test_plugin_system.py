"""Smoke test for the plugin system.

Exercises:
  1. Manifest parsing & validation
  2. Plugin discovery (filesystem scan)
  3. Plugin loading (importlib)
  4. Hook invocation (sync + async)
  5. Aggregate hooks (sidebar panels, etc.)
  6. Enable/disable lifecycle
  7. Event bus pub/sub
  8. Config override
  9. State persistence

Run:  python test_plugin_system.py
"""

import asyncio
import json
import os
import sys
import tempfile
import shutil

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_manifest():
    """Manifest parsing and validation."""
    from plugin_system.schema import Manifest
    from plugin_system.exceptions import PluginManifestError

    # Valid manifest
    m = Manifest.from_dict({
        'name': 'test_plugin',
        'version': '1.0.0',
        'description': {'en': 'Test'},
        'config': {'key': 'value'},
    })
    assert m.name == 'test_plugin'
    assert m.version == '1.0.0'
    assert m.config == {'key': 'value'}
    assert m.enabled is True  # default
    print('[OK] manifest: valid parse')

    # Missing name
    try:
        Manifest.from_dict({'version': '1.0.0'})
        assert False, 'should have raised'
    except PluginManifestError:
        pass
    print('[OK] manifest: missing name rejected')

    # Invalid name (contains dash)
    try:
        Manifest.from_dict({'name': 'bad-name', 'version': '1.0.0'})
        assert False, 'should have raised'
    except PluginManifestError:
        pass
    print('[OK] manifest: invalid name rejected')

    # API version compatibility
    m2 = Manifest.from_dict({'name': 'p', 'version': '1.0.0', 'minApiVersion': '1.0.0'})
    assert m2.api_compatible('1.0.0') is True
    assert m2.api_compatible('2.0.0') is True
    m3 = Manifest.from_dict({'name': 'p', 'version': '1.0.0', 'minApiVersion': '2.0.0'})
    assert m3.api_compatible('1.0.0') is False
    print('[OK] manifest: API version compatibility')


async def test_event_bus():
    """Event bus pub/sub with sync and async handlers."""
    from plugin_system.bus import EventBus

    bus = EventBus()
    received = []

    bus.subscribe('test.event', lambda payload: received.append(('sync', payload)), owner='test')
    print('[OK] bus: sync subscription')

    # Publish (sync handler runs inline)
    n = bus.publish('test.event', {'hello': 'world'})
    assert n == 1, f'expected 1 notification, got {n}'
    assert received == [('sync', {'hello': 'world'})]
    print('[OK] bus: sync publish')

    # Unsubscribe
    assert bus.unsubscribe('test.event', received[0][0] if False else bus._subs['test.event'][0][0])
    n = bus.publish('test.event')
    assert n == 0
    print('[OK] bus: unsubscribe')

    # Async handler
    async def async_handler(payload):
        received.append(('async', payload))

    bus.subscribe('test.async', async_handler, owner='test')
    n = bus.publish('test.async', {'a': 1})
    assert n == 1
    # Async handlers are scheduled on the running loop; await a tick
    await asyncio.sleep(0.05)
    assert ('async', {'a': 1}) in received
    print('[OK] bus: async publish')

    # unsubscribe_all by owner
    bus.subscribe('x', lambda p: None, owner='plugin_a')
    bus.subscribe('y', lambda p: None, owner='plugin_a')
    dropped = bus.unsubscribe_all('plugin_a')
    assert dropped == 2
    print('[OK] bus: unsubscribe_all by owner')


async def test_hooks():
    """Hook dispatcher with sync and async hooks, plus isolation."""
    from plugin_system.hooks import invoke_hook, invoke_all, merge_aggregated, HOOK_NAMES

    # A fake plugin module
    class FakeModule:
        @staticmethod
        def zaowu_app_startup():
            return 'started'

        @staticmethod
        async def zaowu_app_shutdown():
            return 'shutdown'

        @staticmethod
        def zaowu_sidebar_panels():
            return [{'id': 'panel1'}]

        @staticmethod
        def zaowu_on_file_saved(path):
            raise ValueError('intentional')

    # Sync hook
    call = await invoke_hook(FakeModule, 'fake', 'zaowu_app_startup')
    assert call.ok and call.value == 'started'
    print('[OK] hooks: sync invocation')

    # Async hook
    call = await invoke_hook(FakeModule, 'fake', 'zaowu_app_shutdown')
    assert call.ok and call.value == 'shutdown'
    print('[OK] hooks: async invocation')

    # Hook not defined on module
    call = await invoke_hook(FakeModule, 'fake', 'zaowu_plugin_loaded', default='none')
    assert call.ok and call.value == 'none'
    print('[OK] hooks: missing hook returns default')

    # Error isolation — a real hook name that raises
    call = await invoke_hook(FakeModule, 'fake', 'zaowu_on_file_saved', args=('/tmp/x',))
    assert not call.ok
    assert 'intentional' in (call.error or '')
    print('[OK] hooks: error isolation')

    # Aggregate
    class FakeModule2:
        @staticmethod
        def zaowu_sidebar_panels():
            return [{'id': 'panel2'}]

    calls = await invoke_all({'a': FakeModule, 'b': FakeModule2}, 'zaowu_sidebar_panels')
    merged = merge_aggregated(calls)
    assert len(merged) == 2
    assert {m['id'] for m in merged} == {'panel1', 'panel2'}
    print('[OK] hooks: aggregate merge')

    # HOOK_NAMES sanity
    assert 'zaowu_app_startup' in HOOK_NAMES
    assert len(HOOK_NAMES) >= 15
    print(f'[OK] hooks: {len(HOOK_NAMES)} hook names registered')


async def test_manager_lifecycle():
    """Full PluginManager lifecycle with a real temp plugins directory."""
    from plugin_system.manager import PluginManager, get_plugin_manager, set_plugin_manager
    from plugin_system.api import plugin_api

    # Create a temp plugins dir with a minimal plugin
    tmpdir = tempfile.mkdtemp(prefix='zaowu_plugins_test_')
    try:
        plugin_dir = os.path.join(tmpdir, 'my_plugin')
        os.makedirs(plugin_dir)

        with open(os.path.join(plugin_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
            json.dump({
                'name': 'my_plugin',
                'version': '1.0.0',
                'description': {'en': 'Test'},
                'enabled': True,
                'config': {'initial': 'default'},
            }, f)

        with open(os.path.join(plugin_dir, '__init__.py'), 'w', encoding='utf-8') as f:
            f.write(
                "from plugin_system.api import plugin_api\n"
                "from plugin_system.bus import event_bus\n"
                "events = []\n"
                "def zaowu_plugin_loaded():\n"
                "    plugin_api.logger.info('loaded')\n"
                "    events.append('loaded')\n"
                "def zaowu_app_startup():\n"
                "    events.append('startup:' + plugin_api.config.get('initial', '?'))\n"
                "def zaowu_sidebar_panels():\n"
                "    return [{'id': 'my_panel'}]\n"
                "def zaowu_register_routes():\n"
                "    return []\n"
            )

        # Also create a broken plugin (missing __init__.py)
        broken_dir = os.path.join(tmpdir, 'broken_plugin')
        os.makedirs(broken_dir)
        with open(os.path.join(broken_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
            json.dump({'name': 'broken_plugin', 'version': '1.0.0'}, f)

        # Create manager
        mgr = PluginManager(tmpdir)
        set_plugin_manager(mgr)

        # load_all
        loaded, broken = await mgr.load_all()
        assert loaded == 1, f'expected 1 loaded, got {loaded}'
        assert broken == 1, f'expected 1 broken, got {broken}'
        print('[OK] manager: load_all (1 loaded, 1 broken)')

        # Plugin should be enabled (manifest says enabled: true)
        info = mgr.get_plugin('my_plugin')
        assert info is not None
        assert info['enabled'] is True
        print('[OK] manager: plugin enabled on load')

        # Broken plugin reported
        info = mgr.get_plugin('broken_plugin')
        assert info is not None
        assert info['loaded'] is False
        assert 'missing __init__.py' in info['error']
        print('[OK] manager: broken plugin reported')

        # Startup hooks
        await mgr.startup_hooks()
        # The plugin's events list should have 'loaded' and 'startup:default'
        my_module = mgr._records['my_plugin'].module
        assert 'loaded' in my_module.events
        assert 'startup:default' in my_module.events
        print('[OK] manager: startup hooks invoked with config')

        # Aggregate sidebar panels
        panels = await mgr.collect_sidebar_panels()
        assert len(panels) == 1
        assert panels[0]['id'] == 'my_panel'
        print('[OK] manager: aggregate sidebar panels')

        # Config override
        mgr.update_config('my_plugin', {'initial': 'overridden'})
        assert mgr.get_plugin('my_plugin')['config']['initial'] == 'overridden'
        print('[OK] manager: config override')

        # State persistence
        state_path = os.path.join(tmpdir, '.plugin_state.json')
        assert os.path.exists(state_path)
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        assert 'my_plugin' in state['plugins']
        assert state['plugins']['my_plugin']['config']['initial'] == 'overridden'
        print('[OK] manager: state persisted')

        # Disable
        await mgr.disable('my_plugin')
        assert mgr.get_plugin('my_plugin')['enabled'] is False
        print('[OK] manager: disable')

        # Re-enable
        await mgr.enable('my_plugin')
        assert mgr.get_plugin('my_plugin')['enabled'] is True
        print('[OK] manager: re-enable')

        # Shutdown hooks
        await mgr.shutdown_hooks()
        print('[OK] manager: shutdown hooks')

        # Reload
        await mgr.reload('my_plugin')
        assert mgr.get_plugin('my_plugin')['loaded'] is True
        print('[OK] manager: reload')

        # Unload
        await mgr.unload('my_plugin')
        assert mgr.get_plugin('my_plugin') is None
        print('[OK] manager: unload')

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def test_hello_world_plugin():
    """Load the actual hello_world plugin from plugins/."""
    from plugin_system.manager import PluginManager, set_plugin_manager

    plugins_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plugins')
    if not os.path.isdir(os.path.join(plugins_dir, 'hello_world')):
        print('[SKIP] hello_world plugin not found')
        return

    mgr = PluginManager(plugins_dir)
    set_plugin_manager(mgr)

    loaded, broken = await mgr.load_all()
    assert loaded >= 1, f'expected at least 1 plugin, got {loaded}'
    print(f'[OK] hello_world: load_all ({loaded} loaded, {broken} broken)')

    info = mgr.get_plugin('hello_world')
    assert info is not None
    assert info['version'] == '1.0.0'
    assert info['enabled'] is True
    print('[OK] hello_world: manifest parsed')

    # Startup hooks
    await mgr.startup_hooks()
    print('[OK] hello_world: startup hooks')

    # Sidebar panels
    panels = await mgr.collect_sidebar_panels()
    panel_ids = {p['id'] for p in panels}
    assert 'hello_world_panel' in panel_ids
    print(f'[OK] hello_world: sidebar panels = {panel_ids}')

    # Activity bar actions
    actions = await mgr.collect_activity_bar_actions()
    action_ids = {a['id'] for a in actions}
    assert 'hello_world_action' in action_ids
    print(f'[OK] hello_world: activity bar actions = {action_ids}')

    # WS message types
    types = await mgr.collect_ws_message_types()
    assert 'hello_world.ping' in types
    print(f'[OK] hello_world: ws message types = {types}')

    # WS message dispatch
    result = await mgr.dispatch_ws_message('hello_world.ping', {'data': 'test'})
    assert result is not None
    assert result['type'] == 'hello_world.pong'
    print(f'[OK] hello_world: ws dispatch result = {result}')

    # Shutdown
    await mgr.shutdown_hooks()
    print('[OK] hello_world: shutdown hooks')


async def main():
    print('=' * 60)
    print('ZaoWu Plugin System Smoke Test')
    print('=' * 60)

    test_manifest()
    await test_event_bus()
    await test_hooks()
    await test_manager_lifecycle()
    await test_hello_world_plugin()

    print('=' * 60)
    print('ALL TESTS PASSED')
    print('=' * 60)


if __name__ == '__main__':
    asyncio.run(main())
