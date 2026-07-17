# ZaoWu Plugin Development Guide

> This guide is aimed at developers with no prior experience. Starting from a
> minimal example, it progressively covers every capability of the plugin system.
> After reading this guide you will be able to independently write, debug, and
> publish a ZaoWu plugin.

---

## Table of Contents

1. [Quick Start: Create Your First Plugin in 5 Minutes](#1-quick-start-create-your-first-plugin-in-5-minutes)
2. [Plugin Directory Structure](#2-plugin-directory-structure)
3. [manifest.json Manifest File](#3-manifestjson-manifest-file)
4. [Backend Hook Reference](#4-backend-hook-reference)
5. [Frontend Component Extensions](#5-frontend-component-extensions)
6. [plugin_api Service Interface](#6-plugin_api-service-interface)
7. [event_bus Inter-Plugin Communication](#7-event_bus-inter-plugin-communication)
8. [Frontend Event Bus — pluginEventBus](#8-frontend-event-bus--plugineventbus)
9. [Configuration System](#9-configuration-system)
10. [WebSocket Message Extensions](#10-websocket-message-extensions)
11. [Complete Example: Weather Plugin](#11-complete-example-weather-plugin)
12. [Caveats and FAQ](#12-caveats-and-faq)
13. [Plugin API Capability Reference](#13-plugin-api-capability-reference)

---

## 1. Quick Start: Create Your First Plugin in 5 Minutes

### Step 1: Create the directory

Under the `plugins/` folder in the project root, create a new directory named
with **English letters, digits, and underscores**:

```
plugins/
└── my_first_plugin/
```

### Step 2: Create manifest.json

```json
{
  "name": "my_first_plugin",
  "version": "1.0.0",
  "description": {
    "zh-CN": "我的第一个插件",
    "en": "My first plugin"
  },
  "author": "Your Name",
  "minApiVersion": "1.0.0",
  "enabled": true,
  "config": {},
  "frontend": {
    "panels": []
  }
}
```

### Step 3: Create \_\_init\_\_.py

```python
from plugin_system.api import plugin_api


def zaowu_plugin_loaded():
    """Called when the plugin module is imported (once only)."""
    plugin_api.logger.info('my_first_plugin loaded!')


def zaowu_app_startup():
    """Called after the host application has finished starting."""
    plugin_api.logger.info('ZaoWu is ready, my_first_plugin says hello!')
```

### Step 4: Start ZaoWu

After restarting the service, you should see the following in the terminal logs:

```
plugin.my_first_plugin: my_first_plugin loaded!
plugin.my_first_plugin: ZaoWu is ready, my_first_plugin says hello!
```

Congratulations! You have successfully created your first plugin.

---

## 2. Plugin Directory Structure

A complete plugin directory looks like this:

```
plugins/
└── my_plugin/
    ├── manifest.json          # Required — plugin manifest
    ├── __init__.py            # Required — backend entry point (hooks go here)
    └── frontend/              # Optional — frontend Vue components
        ├── Panel.vue          # Sidebar panel component
        ├── Settings.vue       # Settings page component
        └── StatusWidget.vue   # Status bar widget component
```

**Rules:**

- `manifest.json` and `__init__.py` are both required.
- The `frontend/` directory and its `.vue` files are all optional — create them as needed.
- Frontend component filenames must match the `component` field value declared in the hook function (without the `.vue` extension).

---

## 3. manifest.json Manifest File

The manifest file is the plugin's "ID card," describing its metadata and default configuration.

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Plugin identifier; only letters, digits, and underscores are allowed (`^[A-Za-z0-9_]+$`) |
| `version` | string | Yes | Version number; semantic versioning is recommended (e.g. `1.0.0`) |
| `description` | object | No | Multilingual description; keys are locale codes (e.g. `zh-CN`, `en`) |
| `author` | string | No | Author name |
| `minApiVersion` | string | No | Minimum compatible plugin API version; defaults to `"1.0.0"` |
| `enabled` | bool | No | Whether the plugin is enabled by default; defaults to `true` |
| `config` | object | No | Default configuration values; user modifications are persisted in `plugins/.plugin_state.json` |
| `frontend` | object | No | Frontend extension declarations (currently a reserved field; components are registered via hook functions) |

### Example

```json
{
  "name": "weather_widget",
  "version": "2.1.0",
  "description": {
    "zh-CN": "在状态栏显示当前天气",
    "en": "Show current weather in the status bar"
  },
  "author": "ZaoWu Team",
  "minApiVersion": "1.0.0",
  "enabled": true,
  "config": {
    "city": "Beijing",
    "unit": "celsius",
    "refreshInterval": 600
  },
  "frontend": {
    "panels": []
  }
}
```

---

## 4. Backend Hook Reference

Hook functions are the core mechanism for plugins to interact with the host. Simply define functions with specific names in `__init__.py` and the host will automatically call them at the appropriate time. **No decorators or registration calls are needed — hooks are identified purely by function name.**

### 4.1 Lifecycle Hooks

| Hook | When Called | Return Value |
|------|------------|--------------|
| `zaowu_plugin_loaded()` | When the plugin module is first imported | None |
| `zaowu_plugin_enabled()` | When the user enables the plugin | Return `False` to veto |
| `zaowu_plugin_disabled()` | When the user disables the plugin | Return `False` to veto |
| `zaowu_app_startup()` | After the host application has finished starting | None |
| `zaowu_app_shutdown()` | When the host application is about to shut down | None |

**Example:**

```python
from plugin_system.api import plugin_api

def zaowu_plugin_loaded():
    plugin_api.logger.info('loaded')

def zaowu_plugin_enabled():
    # Check whether an optional dependency exists
    try:
        import some_optional_lib
        return True
    except ImportError:
        plugin_api.logger.error('missing dependency: some_optional_lib')
        return False  # Veto the enable

def zaowu_app_startup():
    plugin_api.logger.info('config = %r', plugin_api.config)

def zaowu_app_shutdown():
    plugin_api.logger.info('bye!')
```

### 4.2 File Event Hooks

| Hook | When Called | Parameters |
|------|------------|------------|
| `zaowu_on_file_saved(path)` | When the user saves a file in the editor | `path: str` — file path |
| `zaowu_on_file_deleted(path)` | When a file is deleted | `path: str` |
| `zaowu_on_file_renamed(old, new)` | When a file is renamed | `old: str`, `new: str` |

### 4.3 Collaboration Event Hooks

| Hook | When Called | Parameters |
|------|------------|------------|
| `zaowu_on_user_joined(room_id, user_id)` | When a user joins a collaboration room | `room_id: str` — room ID; `user_id: str` — user ID |
| `zaowu_on_user_left(room_id, user_id)` | When a user leaves a collaboration room | `room_id: str` — room ID; `user_id: str` — user ID |

### 4.4 Frontend Extension Hooks (Aggregate)

The return values of these hooks are **collected and merged** by the host, then pushed to the frontend for rendering. Each hook returns a `list[dict]`.

> **Note:** You do not need to include a `pluginName` field in the return values — the host's `_aggregate()` method automatically injects `pluginName` into each dict item. The frontend uses this field to look up the corresponding Vue component.

| Hook | Purpose | Return Value |
|------|---------|--------------|
| `zaowu_sidebar_panels()` | Register sidebar panels | `[{id, label, icon, component, order}]` |
| `zaowu_activity_bar_actions()` | Register activity bar buttons | `[{id, label, icon, handler, order}]` |
| `zaowu_settings_sections()` | Register settings page sections | `[{id, label, component, icon, order}]` |
| `zaowu_status_bar_items()` | Register status bar widgets | `[{id, component, position, order}]` |
| `zaowu_plugin_detail_sections()` | Register plugin detail page sections | `[{id, label, component, order}]` |

**Field reference:**

```python
def zaowu_sidebar_panels():
    return [{
        'id': 'my_panel',            # Unique identifier
        'label': {                    # Multilingual label
            'zh-CN': '我的面板',
            'en': 'My Panel',
        },
        'icon': 'Smile',             # Lucide icon name
        'component': 'Panel',        # Maps to frontend/Panel.vue
        'order': 100,                # Sort value; lower comes first
    }]


def zaowu_activity_bar_actions():
    return [{
        'id': 'my_action',
        'label': {
            'zh-CN': '我的操作',
            'en': 'My Action',
        },
        'icon': 'Zap',               # Lucide icon name
        'handler': 'my_plugin.click', # Frontend event name, dispatched via pluginEventBus
        'order': 50,
    }]


def zaowu_settings_sections():
    return [{
        'id': 'my_settings',
        'label': {
            'zh-CN': '我的设置',
            'en': 'My Settings',
        },
        'component': 'Settings',     # Maps to frontend/Settings.vue
        'icon': 'Smile',
        'order': 100,
    }]


def zaowu_status_bar_items():
    return [{
        'id': 'my_status',
        'component': 'StatusWidget', # Maps to frontend/StatusWidget.vue
        'position': 'right',         # 'left' or 'right'
        'order': 200,
    }]


def zaowu_plugin_detail_sections():
    return [{
        'id': 'my_detail',
        'label': {
            'zh-CN': '详情',
            'en': 'Details',
        },
        'component': 'DetailSection', # Maps to frontend/DetailSection.vue
        'order': 100,
    }]
```

### 4.5 HTTP Route Registration Hook

| Hook | Purpose | Return Value |
|------|---------|--------------|
| `zaowu_register_routes()` | Register custom HTTP routes | `list[Blueprint]` |

> **Important:** The host does **not** automatically add a prefix to plugin routes. Plugins must explicitly set `url_prefix='/api/plugins/my_plugin'` in their Blueprint for the final path to be `/api/plugins/my_plugin/...`. If you only set `url_prefix='/my_plugin'`, routes will be registered under `/my_plugin/...`.

```python
def zaowu_register_routes():
    from quart import Blueprint, jsonify

    bp = Blueprint('my_plugin', __name__, url_prefix='/api/plugins/my_plugin')

    @bp.route('/hello', methods=['GET'])
    async def hello():
        name = plugin_api.config.get('name', 'World')
        return jsonify({'greeting': f'Hello, {name}!'})

    @bp.route('/projects', methods=['GET'])
    async def list_projects():
        projects = plugin_api.get_projects()
        return jsonify({'count': len(projects), 'projects': projects})

    return [bp]
```

### 4.6 WebSocket Message Hooks

| Hook | Purpose | Return Value |
|------|---------|--------------|
| `zaowu_ws_message_types()` | Declare which WS message types this plugin handles | `list[str]` |
| `zaowu_handle_ws_message(msg_type, payload)` | Handle a WS message | Return a `dict` to broadcast to the room; return `None` to skip |

```python
def zaowu_ws_message_types():
    return ['my_plugin.echo']

def zaowu_handle_ws_message(msg_type, payload):
    if msg_type == 'my_plugin.echo':
        return {
            'type': 'my_plugin.echo_reply',
            'payload': {'original': payload, 'processed': True},
        }
    return None
```

### 4.7 Advanced Hooks

| Hook | Signature | Purpose |
|------|-----------|---------|
| `zaowu_mount_asgi_middleware()` | `() -> None` | Modify the ASGI middleware chain at startup (advanced). Called after `collect_routes` and before `startup_hooks` |
| `zaowu_resolve_host_address(default_host)` | `(default_host: str) -> str \| None` | Customize host address resolution for WebSocket connections (e.g. NAT traversal scenarios). **Must be a sync function** — if defined as `async def`, it will be skipped with a warning. Returning a non-None string replaces the default address; the first plugin returning a valid value wins |

**Example:**

```python
def zaowu_resolve_host_address(default_host: str):
    """NAT traversal scenario: replace the default address with a public domain."""
    if '192.168.' in default_host:
        return 'my-tunnel.example.com:5000'
    return None  # Don't replace
```

---

## 5. Frontend Component Extensions

Plugins can provide Vue 3 single-file components (SFCs) via the `frontend/` directory. The host automatically discovers these components at build time via `import.meta.glob` — no manual registration is needed.

### 5.1 Component Discovery Mechanism

The host scans the `plugins/*/frontend/*.vue` path pattern and registers components in a global registry keyed by `plugin_name:component_name`. When a backend hook returns `component: 'Panel'`, the frontend looks up `plugins/your_plugin/frontend/Panel.vue` and renders it dynamically.

### 5.2 Sidebar Panel (Panel.vue)

When the user clicks the corresponding plugin panel icon in the ActivityBar, the SidePanel renders this component.

```vue
<template>
  <div class="my-panel">
    <h3>{{ title }}</h3>
    <p>Plugin panel content</p>
    <button @click="refresh">Refresh</button>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const title = ref('My Plugin')

async function refresh() {
  // Call the plugin's custom HTTP API
  const res = await fetch('/api/plugins/my_plugin/hello')
  const data = await res.json()
  title.value = data.greeting
}

onMounted(() => refresh())
</script>
```

### 5.3 Status Bar Widget (StatusWidget.vue)

Rendered in the bottom status bar; suitable for displaying brief status information.

```vue
<template>
  <span class="my-status" :title="'My Plugin active'">
    🟢 MP
  </span>
</template>

<style scoped>
.my-status {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-glass);
  margin-right: 4px;
}
</style>
```

### 5.4 Settings Page (Settings.vue)

Rendered in the settings area of the plugin management page; used to modify plugin configuration.

```vue
<template>
  <div class="my-settings">
    <div class="setting-row">
      <label>City Name</label>
      <input v-model="city" @change="save" />
    </div>
    <div v-if="saved" class="saved-msg">Saved</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePluginsStore } from '@/stores/plugins'

const pluginsStore = usePluginsStore()
const city = ref('')
const saved = ref(false)

onMounted(async () => {
  await pluginsStore.fetchPlugins()
  const p = pluginsStore.plugins.find(p => p.name === 'my_plugin')
  if (p) city.value = p.config.city ?? ''
})

async function save() {
  await pluginsStore.updateConfig('my_plugin', { city: city.value })
  saved.value = true
  setTimeout(() => { saved.value = false }, 1500)
}
</script>
```

### 5.5 Plugin Detail Page Section (DetailSection.vue)

Rendered in the plugin management detail page (after the log section). Useful for displaying additional plugin-related information such as README, runtime status, or statistics. The host sorts and renders sections returned by multiple plugins according to `order`.

```vue
<template>
  <div class="my-detail-section">
    <p>Plugin detail page extension content</p>
    <button @click="refresh">Refresh</button>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const count = ref(0)

async function refresh() {
  const res = await fetch('/api/plugins/my_plugin/stats')
  const data = await res.json()
  count.value = data.count ?? 0
}

onMounted(() => refresh())
</script>

<style scoped>
.my-detail-section { padding: 12px; }
</style>
```

### 5.6 Available Lucide Icons

Icons used by the ActivityBar and settings pages come from [lucide](https://lucide.dev). The host pre-imports the following icons for plugins to use:

`MessageSquare` `FolderTree` `Search` `GitBranch` `Puzzle` `Users` `Settings` `Zap` `Smile` `Bell` `Star` `Heart` `AlertCircle`

If a plugin declares an icon name that is not pre-imported, it will automatically fall back to the `Puzzle` icon.

### 5.6 CSS Variables

Plugin components should use the host-provided CSS variables to maintain theme consistency:

| Variable | Purpose |
|----------|---------|
| `var(--text-primary)` | Primary text color |
| `var(--text-secondary)` | Secondary text color |
| `var(--text-tertiary)` | Tertiary text color |
| `var(--bg-primary)` | Primary background color |
| `var(--bg-secondary)` | Secondary background color |
| `var(--bg-glass)` | Glass-style background |
| `var(--bg-glass-hover)` | Glass-style hover background |
| `var(--bg-glass-active)` | Glass-style active background |
| `var(--border-subtle)` | Border color |
| `var(--border-glass)` | Glass-style border color |
| `var(--accent)` | Accent color |
| `var(--accent-hover)` | Accent hover color |
| `var(--accent-muted)` | Muted accent color |
| `var(--success)` | Success color |
| `var(--danger)` | Danger/error color |
| `var(--transition)` | Transition animation |

---

## 6. plugin_api Service Interface

`plugin_api` is the sole entry point for plugins to access host services. It is a process-wide singleton that uses a ContextVar to automatically bind the current plugin's context (config, logger, name) inside hook functions.

### 6.1 Import

```python
from plugin_system.api import plugin_api
```

### 6.2 Properties (only available inside hook functions)

| Property | Type | Description |
|----------|------|-------------|
| `plugin_api.name` | `str` | Current plugin name |
| `plugin_api.config` | `dict` | Merged config for the current plugin (manifest defaults + user overrides) |
| `plugin_api.logger` | `Logger` | Standard library logger namespaced as `plugin.<name>` |

> ⚠️ These three properties are implemented via Python's `contextvars.ContextVar` and **can only be accessed during hook function calls**. Accessing them at module top level or in other non-hook contexts will raise a `RuntimeError`. If you need to use them in a callback, capture the values into local variables inside the hook first.

### 6.3 Methods

| Method | Description |
|--------|-------------|
| `plugin_api.get_projects()` | Returns the list of all registered projects as `list[dict]`; each dict contains `id`, `path`, etc. |
| `plugin_api.get_setting(key, default)` | Read a value from the host `settings.json`; `default` is returned if the key is not found |
| `plugin_api.get_app()` | Get the Quart app instance (advanced) |
| `plugin_api.get_room_service()` | Get the collaboration room service module |
| `plugin_api.broadcast_to_room(room_id, payload)` | Broadcast a custom JSON message to a collaboration room (async) |
| `plugin_api.register_blueprint(bp, url_prefix)` | Register a Quart Blueprint (use inside the `zaowu_register_routes` hook) |
| `plugin_api.start_subprocess(*args, **kwargs)` | Start a subprocess; the host automatically terminates it when the plugin is disabled or the app shuts down |

### 6.4 Usage Example

```python
from plugin_system.api import plugin_api

def zaowu_app_startup():
    # Read config
    city = plugin_api.config.get('city', 'Beijing')
    plugin_api.logger.info('monitoring weather for %s', city)

    # Read host settings
    theme = plugin_api.get_setting('theme', 'dark')

    # Get project list
    projects = plugin_api.get_projects()
    plugin_api.logger.info('found %d projects', len(projects))

async def zaowu_on_file_saved(path):
    # Broadcast file save event to the collaboration room
    await plugin_api.broadcast_to_room('main', {
        'type': 'plugin.file_saved',
        'payload': {'path': path},
    })
```

---

## 7. event_bus Inter-Plugin Communication

`event_bus` is an in-process publish/subscribe bus for **horizontal communication between plugins**. The host itself does not use this bus.

### 7.1 Import

```python
from plugin_system.bus import event_bus
```

### 7.2 API

| Method | Description |
|--------|-------------|
| `event_bus.subscribe(event_name, handler, owner)` | Subscribe to an event. `handler` can be a regular function or an async function. `owner` is the plugin name (defaults to `'?'`); used for automatic cleanup on disable |
| `event_bus.unsubscribe(event_name, handler)` | Remove a single subscription |
| `event_bus.unsubscribe_all(owner)` | Remove all subscriptions for a given plugin |
| `event_bus.publish(event_name, payload)` | Publish an event. Sync handlers run inline; async handlers are scheduled on the event loop |
| `event_bus.publish_async(event_name, payload)` | Async publish; awaits all async handlers to completion |

### 7.3 Usage Example

```python
# Plugin A: publish an event
from plugin_system.bus import event_bus

def zaowu_app_startup():
    event_bus.publish('weather.updated', {
        'city': 'Beijing',
        'temp': 25,
    })


# Plugin B: subscribe to an event
from plugin_system.bus import event_bus

def _on_weather_updated(payload):
    print(f"Weather: {payload['city']} {payload['temp']}°C")

def zaowu_app_startup():
    event_bus.subscribe('weather.updated', _on_weather_updated, owner='my_plugin')

def zaowu_app_shutdown():
    event_bus.unsubscribe_all('my_plugin')
```

> **Tip:** Although the host automatically calls `unsubscribe_all` when a plugin is disabled, it is good practice to explicitly clean up in `zaowu_app_shutdown`.

---

## 8. Frontend Event Bus — pluginEventBus

When the user clicks a plugin button in the ActivityBar, the host dispatches an event via the frontend event bus. Plugin frontend code can listen for these events.

### 8.1 How It Works

1. The plugin declares `handler: 'my_plugin.click'` in `zaowu_activity_bar_actions()`
2. The user clicks the button
3. The host calls `pluginEventBus.emit('my_plugin.click', {...})`
4. The plugin's frontend component responds via `pluginEventBus.on('my_plugin.click', callback)`

### 8.2 Frontend Usage

```vue
<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { pluginEventBus } from '@/plugin-system/events'

function handleClick(payload: any) {
  console.log('Button clicked!', payload)
  // Your logic here...
}

onMounted(() => {
  pluginEventBus.on('my_plugin.click', handleClick)
})

onUnmounted(() => {
  pluginEventBus.off('my_plugin.click', handleClick)
})
</script>
```

### 8.3 API

| Method | Description |
|--------|-------------|
| `pluginEventBus.on(event, handler)` | Listen for an event |
| `pluginEventBus.off(event, handler)` | Remove a listener |
| `pluginEventBus.emit(event, payload?)` | Emit an event |

---

## 9. Configuration System

### 9.1 Configuration Sources and Merging

Plugin configuration has two sources that are automatically merged at runtime:

1. **Manifest defaults** — the `config` field in `manifest.json`
2. **User overrides** — values modified by the user via the settings page or API; persisted in `plugins/.plugin_state.json`

Merge rule: user overrides take precedence over manifest defaults. Access the merged result via `plugin_api.config` inside hook functions.

### 9.2 Reading Configuration

```python
def zaowu_app_startup():
    cfg = plugin_api.config
    city = cfg.get('city', 'Beijing')       # With a fallback default
    unit = cfg.get('unit', 'celsius')
    interval = cfg.get('refreshInterval', 300)
    plugin_api.logger.info('city=%s unit=%s interval=%d', city, unit, interval)
```

### 9.3 Modifying Configuration from the Frontend

Use the `updateConfig` method from `usePluginsStore`:

```typescript
import { usePluginsStore } from '@/stores/plugins'

const pluginsStore = usePluginsStore()
await pluginsStore.updateConfig('my_plugin', {
  city: 'Shanghai',
  unit: 'fahrenheit',
})
```

---

## 10. WebSocket Message Extensions

Plugins can register custom WebSocket message types to enable real-time bidirectional communication.

### 10.1 Flow

1. The plugin declares which message types it handles via `zaowu_ws_message_types()`
2. When the frontend sends a WS message matching a declared type, the host calls `zaowu_handle_ws_message(msg_type, payload)`
3. If the handler returns a dict, the host broadcasts it to all clients in the room

### 10.2 Complete Example

```python
def zaowu_ws_message_types():
    """Declare WS message types this plugin handles."""
    return ['my_plugin.query']

def zaowu_handle_ws_message(msg_type, payload):
    """Handle a WS message. Return a dict to broadcast; return None to skip."""
    if msg_type == 'my_plugin.query':
        result = do_something(payload)
        return {
            'type': 'my_plugin.result',
            'payload': result,
        }
    return None
```

---

## 11. Complete Example: Weather Plugin

Below is a full-featured weather plugin example that demonstrates most plugin capabilities.

### Directory Structure

```
plugins/
└── weather_widget/
    ├── manifest.json
    ├── __init__.py
    └── frontend/
        ├── Panel.vue
        ├── StatusWidget.vue
        └── Settings.vue
```

### manifest.json

```json
{
  "name": "weather_widget",
  "version": "1.0.0",
  "description": {
    "zh-CN": "在侧栏和状态栏展示天气信息",
    "en": "Display weather info in sidebar and status bar"
  },
  "author": "Your Name",
  "minApiVersion": "1.0.0",
  "enabled": true,
  "config": {
    "city": "Beijing",
    "unit": "celsius"
  },
  "frontend": {
    "panels": []
  }
}
```

### \_\_init\_\_.py

```python
"""Weather plugin — demonstrates the complete plugin development flow."""

from plugin_system.api import plugin_api
from plugin_system.bus import event_bus


# ── Lifecycle ──────────────────────────────────────────────────────

def zaowu_plugin_loaded():
    plugin_api.logger.info('weather_widget loaded')


def zaowu_app_startup():
    city = plugin_api.config.get('city', 'Beijing')
    plugin_api.logger.info('monitoring weather for %s', city)
    # Publish an event that other plugins can subscribe to
    event_bus.publish('weather.ready', {'city': city})


def zaowu_app_shutdown():
    event_bus.unsubscribe_all('weather_widget')
    plugin_api.logger.info('weather_widget shutdown')


# ── File events ────────────────────────────────────────────────────

def zaowu_on_file_saved(path: str):
    plugin_api.logger.debug('file saved: %s', path)


# ── HTTP routes ────────────────────────────────────────────────────

def zaowu_register_routes():
    from quart import Blueprint, jsonify

    bp = Blueprint('weather_widget', __name__, url_prefix='/api/plugins/weather')

    @bp.route('/current', methods=['GET'])
    async def current_weather():
        cfg = plugin_api.config
        return jsonify({
            'ok': True,
            'city': cfg.get('city', 'Beijing'),
            'temp': 22,
            'unit': cfg.get('unit', 'celsius'),
            'condition': 'sunny',
        })

    return [bp]


# ── Frontend extensions ────────────────────────────────────────────

def zaowu_sidebar_panels():
    return [{
        'id': 'weather_panel',
        'label': {'zh-CN': '天气', 'en': 'Weather'},
        'icon': 'Star',
        'component': 'Panel',
        'order': 50,
    }]


def zaowu_activity_bar_actions():
    return [{
        'id': 'weather_refresh',
        'label': {'zh-CN': '刷新天气', 'en': 'Refresh Weather'},
        'icon': 'Zap',
        'handler': 'weather_widget.refresh',
        'order': 60,
    }]


def zaowu_status_bar_items():
    return [{
        'id': 'weather_status',
        'component': 'StatusWidget',
        'position': 'right',
        'order': 100,
    }]


def zaowu_settings_sections():
    return [{
        'id': 'weather_settings',
        'label': {'zh-CN': '天气设置', 'en': 'Weather Settings'},
        'component': 'Settings',
        'icon': 'Star',
        'order': 50,
    }]
```

### frontend/Panel.vue

```vue
<template>
  <div class="weather-panel">
    <div class="weather-city">{{ city }}</div>
    <div class="weather-temp">{{ temp }}°{{ unit === 'celsius' ? 'C' : 'F' }}</div>
    <div class="weather-condition">{{ condition }}</div>
    <button @click="refresh" class="weather-btn">Refresh</button>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { pluginEventBus } from '@/plugin-system/events'

const city = ref('--')
const temp = ref(0)
const unit = ref('celsius')
const condition = ref('--')

async function refresh() {
  try {
    const res = await fetch('/api/plugins/weather/current')
    const data = await res.json()
    if (data.ok) {
      city.value = data.city
      temp.value = data.temp
      unit.value = data.unit
      condition.value = data.condition
    }
  } catch { /* ignore */ }
}

onMounted(() => {
  refresh()
  pluginEventBus.on('weather_widget.refresh', refresh)
})

onUnmounted(() => {
  pluginEventBus.off('weather_widget.refresh', refresh)
})
</script>

<style scoped>
.weather-panel { padding: 12px; }
.weather-city { font-size: 16px; font-weight: 600; color: var(--text-primary); }
.weather-temp { font-size: 24px; font-weight: 700; color: var(--accent); margin: 8px 0; }
.weather-condition { font-size: 13px; color: var(--text-secondary); }
.weather-btn {
  margin-top: 8px; padding: 6px 14px;
  border: 1px solid var(--border-subtle); border-radius: 6px;
  background: var(--bg-glass); color: var(--text-secondary);
  font-size: 12px; cursor: pointer;
}
.weather-btn:hover { background: var(--bg-glass-hover); color: var(--text-primary); }
</style>
```

### frontend/StatusWidget.vue

```vue
<template>
  <span class="weather-status" :title="`Weather: ${city} ${temp}°`">
    ☀️ {{ temp }}°
  </span>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const city = ref('')
const temp = ref(0)

async function refresh() {
  try {
    const res = await fetch('/api/plugins/weather/current')
    const data = await res.json()
    if (data.ok) {
      city.value = data.city
      temp.value = data.temp
    }
  } catch { /* ignore */ }
}

onMounted(() => refresh())
</script>

<style scoped>
.weather-status {
  font-size: 10px; color: var(--text-tertiary);
  background: var(--bg-glass); padding: 1px 6px;
  border-radius: 4px; border: 1px solid var(--border-glass);
  margin-right: 4px;
}
</style>
```

### frontend/Settings.vue

```vue
<template>
  <div class="weather-settings">
    <div class="setting-row">
      <label>City</label>
      <input v-model="city" @change="save" />
    </div>
    <div class="setting-row">
      <label>Unit</label>
      <select v-model="unit" @change="save">
        <option value="celsius">Celsius °C</option>
        <option value="fahrenheit">Fahrenheit °F</option>
      </select>
    </div>
    <div v-if="saved" class="saved-msg">Saved</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePluginsStore } from '@/stores/plugins'

const pluginsStore = usePluginsStore()
const city = ref('')
const unit = ref('celsius')
const saved = ref(false)

onMounted(async () => {
  await pluginsStore.fetchPlugins()
  const p = pluginsStore.plugins.find(p => p.name === 'weather_widget')
  if (p) {
    city.value = p.config.city ?? 'Beijing'
    unit.value = p.config.unit ?? 'celsius'
  }
})

async function save() {
  await pluginsStore.updateConfig('weather_widget', {
    city: city.value,
    unit: unit.value,
  })
  saved.value = true
  setTimeout(() => { saved.value = false }, 1500)
}
</script>

<style scoped>
.weather-settings { padding: 12px; display: flex; flex-direction: column; gap: 12px; }
.setting-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.setting-row label { font-size: 13px; color: var(--text-primary); }
.setting-row input, .setting-row select {
  background: var(--bg-primary); border: 1px solid var(--border-subtle);
  border-radius: 6px; color: var(--text-primary); font-size: 13px; padding: 4px 8px; width: 180px;
}
.setting-row input:focus, .setting-row select:focus { outline: none; border-color: var(--accent); }
.saved-msg { font-size: 12px; color: var(--success); }
</style>
```

---

## 12. Caveats and FAQ

### 12.1 Naming Rules

- Plugin directory names (i.e. plugin names) **only allow English letters, digits, and underscores** — Chinese characters, hyphens, and other special characters are not supported.
- Frontend component filenames must exactly match the `component` field value in hook functions (case-sensitive).

### 12.2 plugin_api Scope Restrictions

The `plugin_api.name`, `plugin_api.config`, and `plugin_api.logger` properties are implemented via Python's `contextvars.ContextVar` and **can only be used during hook function calls**. The following scenarios will raise a `RuntimeError`:

```python
# ❌ Wrong: accessing at module top level
from plugin_system.api import plugin_api
print(plugin_api.config)  # RuntimeError!

# ❌ Wrong: accessing in an async callback (left the hook call stack)
async def zaowu_app_startup():
    async def callback():
        print(plugin_api.config)  # RuntimeError!
    asyncio.create_task(callback())

# ✅ Correct: capture into a local variable inside the hook
async def zaowu_app_startup():
    cfg = dict(plugin_api.config)  # Capture a snapshot
    async def callback():
        print(cfg)  # OK
    asyncio.create_task(callback())
```

### 12.3 Error Isolation

The plugin system wraps every hook call in `try/except` isolation. **An exception thrown by one plugin will not affect the host or other plugins.** Exceptions are logged; plugin developers should monitor the `plugin.<name>` namespace log output.

### 12.4 Hooks Must Be Sync or Async

Hook functions can be regular functions or `async def` — the host handles both automatically. But **do not use `await` inside a regular (non-async) function**.

### 12.5 Hot Reload

During development, you can hot-reload a plugin via the API call `POST /api/plugins/<name>/reload` without restarting the entire service. The plugin's enabled state and user configuration are preserved after reload.

### 12.6 Disable and Uninstall

- **Disable** (`POST /api/plugins/<name>/disable`): Calls the `zaowu_plugin_disabled` hook, terminates subprocesses, and cleans up event bus subscriptions. The plugin directory is preserved.
- **Uninstall** (`DELETE /api/plugins/<name>`): First disables the plugin, then renames the plugin directory to `<name>.disabled` (files are not deleted, allowing recovery).

### 12.7 Subprocess Management

Subprocesses started via `plugin_api.start_subprocess()` are tracked by the host and automatically terminated when the plugin is disabled or the application shuts down. **Do not use `subprocess.Popen` directly** — otherwise the host cannot track and clean up the process.

### 12.8 Two Ways to Register Routes

The `zaowu_register_routes` hook supports two registration methods, and the host handles both:

1. **Return a list of Blueprints** (recommended) — the host automatically calls `register_blueprint`
2. **Manually call `plugin_api.register_blueprint()` inside the hook** — useful when a dynamic prefix is needed

### 12.9 Build-Time Frontend Component Discovery

Frontend components are scanned at build time via Vite's `import.meta.glob`. This means:

- **You must rebuild the frontend after adding a new plugin** for it to be discovered.
- Component paths must match the `plugins/*/frontend/*.vue` pattern.
- Components are loaded as async components (`defineAsyncComponent`) and do not block the initial render.

### 12.10 Configuration Persistence

User-modified configuration is saved in `plugins/.plugin_state.json` with the following format:

```json
{
  "version": 1,
  "plugins": {
    "my_plugin": {
      "enabled": true,
      "config": {
        "city": "Shanghai"
      }
    }
  }
}
```

After manually editing this file, restart the service for changes to take effect.

---

## 13. Plugin API Capability Reference

### Backend Capabilities

| Capability | Interface/Hook | Description |
|------------|----------------|-------------|
| Read own config | `plugin_api.config` | Merged config dict |
| Logging | `plugin_api.logger.info/warning/error(...)` | Namespace `plugin.<name>` |
| Get project list | `plugin_api.get_projects()` | Equivalent to `/api/explorer/projects` |
| Read host settings | `plugin_api.get_setting(key, default)` | Reads `settings.json`; `default` is the fallback |
| Register HTTP routes | `zaowu_register_routes()` + `plugin_api.register_blueprint()` | Set `url_prefix='/api/plugins/<name>'` in the Blueprint |
| Register frontend panel | `zaowu_sidebar_panels()` | Sidebar panel |
| Register toolbar button | `zaowu_activity_bar_actions()` | ActivityBar icon button |
| Register settings section | `zaowu_settings_sections()` | Settings page section |
| Register status bar item | `zaowu_status_bar_items()` | Bottom status bar |
| Register plugin detail page section | `zaowu_plugin_detail_sections()` | Plugin management detail page section |
| Inter-plugin communication | `event_bus.subscribe/publish` | In-process event bus |
| WebSocket messages | `zaowu_ws_message_types()` + `zaowu_handle_ws_message()` | Real-time bidirectional communication |
| Broadcast to room | `await plugin_api.broadcast_to_room(room_id, payload)` | Collaboration room broadcast |
| Start subprocess | `plugin_api.start_subprocess(...)` | Auto-tracked and cleaned up |
| Get Quart app | `plugin_api.get_app()` | Advanced use |

### Frontend Capabilities

| Capability | Interface | Description |
|------------|-----------|-------------|
| Listen for plugin button clicks | `pluginEventBus.on(event, handler)` | ActivityBar button events |
| Read plugin config | `usePluginsStore().fetchPlugins()` | Pinia store |
| Modify plugin config | `usePluginsStore().updateConfig(name, config)` | Persisted to server |
| Use host CSS variables | `var(--text-primary)` etc. | Auto-adapts to dark/light themes |

---

## Appendix: hello_world Example Plugin

The built-in `plugins/hello_world/` is a reference implementation that demonstrates the minimal usage of core capabilities including lifecycle, frontend extensions (panel/activity bar/status bar/settings), HTTP routes, WebSocket messages, and the event bus. You can copy it as a starting point when developing a new plugin:

```bash
cp -r plugins/hello_world plugins/my_plugin
```

Then modify the `name` in `manifest.json` and the logic in `__init__.py`.

---

> For further questions, refer to `plugins/PLUGIN_SYSTEM.md` (architecture design document) or read the source code in the `plugin_system/` directory.
