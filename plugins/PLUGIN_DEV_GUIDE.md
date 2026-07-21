# ZaoWu 插件开发教程

> 本教程面向零基础开发者，从一个最小示例开始，逐步覆盖插件系统的所有能力。
> 阅读完毕后你将能够独立编写、调试和发布一个 ZaoWu 插件。

---

## 目录

1. [快速开始：5 分钟创建你的第一个插件](#1-快速开始5-分钟创建你的第一个插件)
2. [插件目录结构](#2-插件目录结构)
3. [manifest.json 清单文件](#3-manifestjson-清单文件)
4. [后端钩子函数一览](#4-后端钩子函数一览)
5. [前端组件扩展](#5-前端组件扩展)
6. [plugin_api 服务接口](#6-plugin_api-服务接口)
7. [event_bus 插件间通信](#7-event_bus-插件间通信)
8. [前端事件总线 pluginEventBus](#8-前端事件总线-plugineventbus)
9. [配置系统](#9-配置系统)
10. [WebSocket 消息扩展](#10-websocket-消息扩展)
11. [完整示例：天气插件](#11-完整示例天气插件)
12. [注意事项与常见问题](#12-注意事项与常见问题)
13. [插件 API 能力速查表](#13-插件-api-能力速查表)
14. [安全注意事项](#14-安全注意事项)

---

## 1. 快速开始：5 分钟创建你的第一个插件

### 第一步：创建目录

在项目根目录的 `plugins/` 文件夹下新建一个以**英文字母、数字、下划线**命名的目录：

```
plugins/
└── my_first_plugin/
```

### 第二步：创建 manifest.json

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

### 第三步：创建 \_\_init\_\_.py

```python
from plugin_system.api import plugin_api


def zaowu_plugin_loaded():
    """插件模块被导入时调用（仅一次）。"""
    plugin_api.logger.info('my_first_plugin loaded!')


def zaowu_app_startup():
    """宿主应用启动完成后调用。"""
    plugin_api.logger.info('ZaoWu is ready, my_first_plugin says hello!')
```

### 第四步：启动 ZaoWu

重启服务后，在终端日志中你应该能看到：

```
plugin.my_first_plugin: my_first_plugin loaded!
plugin.my_first_plugin: ZaoWu is ready, my_first_plugin says hello!
```

恭喜！你已经成功创建了第一个插件。

---

## 2. 插件目录结构

一个完整的插件目录如下所示：

```
plugins/
└── my_plugin/
    ├── manifest.json          # 必须 — 插件清单
    ├── __init__.py            # 必须 — 后端入口（钩子函数写在这里）
    └── frontend/              # 可选 — 前端 Vue 组件
        ├── Panel.vue          # 侧栏面板组件（源码）
        ├── Settings.vue       # 设置页面组件（源码）
        ├── StatusWidget.vue   # 状态栏小部件组件（源码）
        └── dist/              # 构建产物（运行时安装时必需）
            ├── _manifest.json # 组件名 → bundle 路径映射
            ├── Panel.js       # 编译后的自包含 JS bundle
            ├── Settings.js
            └── StatusWidget.js
```

**规则：**

- `manifest.json` 和 `__init__.py` 是必须的，缺一不可。
- `frontend/` 目录及其 `.vue` 文件均为可选，按需创建。
- 前端组件的文件名必须与钩子函数中 `component` 字段的值对应（不含 `.vue` 后缀）。
- `frontend/dist/` 是构建产物，通过 `scripts/build-plugin-frontend.js` 生成。**运行时安装的插件必须包含此目录**，构建时已有的插件可直接使用 `.vue` 源码。

---

## 3. manifest.json 清单文件

清单文件是插件的"身份证"，描述了插件的元信息和默认配置。

### 字段说明

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 插件标识符，仅允许字母、数字、下划线（`^[A-Za-z0-9_]+$`） |
| `version` | string | ✅ | 版本号，推荐语义化版本（如 `1.0.0`） |
| `description` | object | — | 多语言描述，key 为 locale（如 `zh-CN`、`en`） |
| `author` | string | — | 作者名 |
| `minApiVersion` | string | — | 最低兼容的插件 API 版本，默认 `"1.0.0"` |
| `enabled` | bool | — | 默认是否启用，默认 `true` |
| `config` | object | — | 默认配置值，用户修改后保存在 `plugins/.plugin_state.json` |
| `frontend` | object | — | 前端扩展声明（目前为预留字段，组件通过钩子函数注册） |
| `frontendBundles` | object | — | 前端组件名 → JS bundle 路径映射，运行时安装的插件需声明此字段 |

### 示例

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
  },
  "frontendBundles": {
    "Panel": "frontend/dist/Panel.js",
    "StatusWidget": "frontend/dist/StatusWidget.js"
  }
}
```

---

## 4. 后端钩子函数一览

钩子函数是插件与宿主交互的核心机制。只需在 `__init__.py` 中定义特定名称的函数，宿主会在合适的时机自动调用它们。**不需要任何装饰器或注册操作——纯靠函数名识别。**

### 4.1 生命周期钩子

| 钩子函数 | 调用时机 | 返回值 |
|----------|----------|--------|
| `zaowu_plugin_loaded()` | 插件模块首次被导入 | 无 |
| `zaowu_plugin_enabled()` | 用户启用插件时 | 返回 `False` 可拒绝启用 |
| `zaowu_plugin_disabled()` | 用户禁用插件时 | 返回 `False` 可拒绝禁用 |
| `zaowu_app_startup()` | 宿主应用启动完成后 | 无 |
| `zaowu_app_shutdown()` | 宿主应用即将关闭时 | 无 |

**示例：**

```python
from plugin_system.api import plugin_api

def zaowu_plugin_loaded():
    plugin_api.logger.info('loaded')

def zaowu_plugin_enabled():
    # 检查外部依赖是否存在
    try:
        import some_optional_lib
        return True
    except ImportError:
        plugin_api.logger.error('missing dependency: some_optional_lib')
        return False  # 拒绝启用

def zaowu_app_startup():
    plugin_api.logger.info('config = %r', plugin_api.config)

def zaowu_app_shutdown():
    plugin_api.logger.info('bye!')
```

### 4.2 文件事件钩子

| 钩子函数 | 调用时机 | 参数 |
|----------|----------|------|
| `zaowu_on_file_saved(path)` | 用户在编辑器中保存文件 | `path: str` — 文件路径 |
| `zaowu_on_file_deleted(path)` | 文件被删除 | `path: str` |
| `zaowu_on_file_renamed(old, new)` | 文件被重命名 | `old: str`, `new: str` |

### 4.3 协作事件钩子

| 钩子函数 | 调用时机 | 参数 |
|----------|----------|------|
| `zaowu_on_user_joined(room_id, user_id)` | 用户加入协作房间 | `room_id: str` — 房间 ID；`user_id: str` — 用户 ID |
| `zaowu_on_user_left(room_id, user_id)` | 用户离开协作房间 | `room_id: str` — 房间 ID；`user_id: str` — 用户 ID |

### 4.4 前端扩展钩子（聚合类）

这些钩子的返回值会被宿主**收集并合并**，推送到前端渲染。每个钩子返回一个 `list[dict]`。

> **注意**：无需在返回值中包含 `pluginName` 字段——宿主的 `_aggregate()` 方法会自动为每个 dict 项注入 `pluginName`，前端通过该字段查找对应的 Vue 组件。

| 钩子函数 | 作用 | 返回值 |
|----------|------|--------|
| `zaowu_sidebar_panels()` | 注册侧栏面板 | `[{id, label, icon, component, order}]` |
| `zaowu_activity_bar_actions()` | 注册左侧工具栏按钮 | `[{id, label, icon, handler, order}]` |
| `zaowu_settings_sections()` | 注册设置页面分区 | `[{id, label, component, icon, order}]` |
| `zaowu_status_bar_items()` | 注册状态栏小部件 | `[{id, component, position, order}]` |
| `zaowu_plugin_detail_sections()` | 注册插件详情页分区 | `[{id, label, component, order}]` |

**各字段说明：**

```python
def zaowu_sidebar_panels():
    return [{
        'id': 'my_panel',            # 唯一标识
        'label': {                    # 多语言标签
            'zh-CN': '我的面板',
            'en': 'My Panel',
        },
        'icon': 'Smile',             # lucide 图标名
        'component': 'Panel',        # 对应 frontend/Panel.vue
        'order': 100,                # 排序值，越小越靠前
    }]


def zaowu_activity_bar_actions():
    return [{
        'id': 'my_action',
        'label': {
            'zh-CN': '我的操作',
            'en': 'My Action',
        },
        'icon': 'Zap',               # lucide 图标名
        'handler': 'my_plugin.click', # 前端事件名，通过 pluginEventBus 派发
        'order': 50,
    }]


def zaowu_settings_sections():
    return [{
        'id': 'my_settings',
        'label': {
            'zh-CN': '我的设置',
            'en': 'My Settings',
        },
        'component': 'Settings',     # 对应 frontend/Settings.vue
        'icon': 'Smile',
        'order': 100,
    }]


def zaowu_status_bar_items():
    return [{
        'id': 'my_status',
        'component': 'StatusWidget', # 对应 frontend/StatusWidget.vue
        'position': 'right',         # 'left' 或 'right'
        'order': 200,
    }]


def zaowu_plugin_detail_sections():
    return [{
        'id': 'my_detail',
        'label': {
            'zh-CN': '详情',
            'en': 'Details',
        },
        'component': 'DetailSection', # 对应 frontend/DetailSection.vue
        'order': 100,
    }]
```

### 4.5 HTTP 路由注册钩子

| 钩子函数 | 作用 | 返回值 |
|----------|------|--------|
| `zaowu_register_routes()` | 注册自定义 HTTP 路由 | `list[Blueprint]` |

> **重要**：宿主**不会**自动为插件路由添加前缀。插件需在 Blueprint 中显式设置 `url_prefix='/api/plugins/my_plugin'`，最终路径才为 `/api/plugins/my_plugin/...`。如果仅设置 `url_prefix='/my_plugin'`，路由将注册在 `/my_plugin/...` 下。

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

> **⚠️ 安全提示：输入校验**
>
> 插件路由**必须**对所有 `request.get_json()` 输入进行校验，不要直接 `data.get('key', '')` 取值后使用。
> 项目提供 `services/input_validation.py` 工具模块，支持类型检查、长度限制、路径安全校验等：
>
> ```python
> from services.input_validation import require_str, require_path, require_command, validate_json_body
>
> @bp.route('/exec', methods=['POST'])
> async def exec_cmd():
>     data = await request.get_json(silent=True)
>     ok, err = validate_json_body(data)          # 校验非空 dict
>     if not ok:
>         return jsonify({'ok': False, 'error': err}), 400
>     ok, err = require_str(data, 'name', max_len=100)  # 校验字符串字段
>     if not ok:
>         return jsonify({'ok': False, 'error': err}), 400
>     ok, err = require_path(data, 'path')         # 校验路径字段（防 null 字节注入）
>     if not ok:
>         return jsonify({'ok': False, 'error': err}), 400
>     # ... 安全使用 data['name'] 和 data['path']
> ```
>
> 详见 [第 14 节：安全注意事项](#14-安全注意事项)。

### 4.6 WebSocket 消息钩子

| 钩子函数 | 作用 | 返回值 |
|----------|------|--------|
| `zaowu_ws_message_types()` | 声明本插件处理的 WS 消息类型 | `list[str]` |
| `zaowu_handle_ws_message(msg_type, payload)` | 处理 WS 消息 | 返回 `dict` 广播给房间，返回 `None` 不广播 |

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

### 4.7 高级钩子

| 钩子函数 | 签名 | 作用 |
|----------|------|------|
| `zaowu_mount_asgi_middleware()` | `() -> None` | 在应用启动时修改 ASGI 中间件链（高级用法）。在 `collect_routes` 之后、`startup_hooks` 之前调用 |
| `zaowu_resolve_host_address(default_host)` | `(default_host: str) -> str \| None` | 自定义 WebSocket 连接的宿主地址解析（如内网穿透场景）。**必须为同步函数**，若定义为 `async def` 会被跳过并警告。返回非 None 字符串则替换默认地址，第一个返回有效值的插件胜出 |

**示例：**

```python
def zaowu_resolve_host_address(default_host: str):
    """内网穿透场景：将默认地址替换为公网域名。"""
    if '192.168.' in default_host:
        return 'my-tunnel.example.com:5000'
    return None  # 不替换
```

---

## 5. 前端组件扩展

插件可以通过 `frontend/` 目录提供 Vue 3 单文件组件（SFC）。宿主采用**双轨加载机制**：

1. **构建时加载**：宿主构建时通过 `import.meta.glob` 自动发现 `plugins/*/frontend/*.vue`，打包进主应用。适用于随应用分发的内置插件。
2. **运行时加载**：构建后安装的插件通过 `frontend/dist/` 中的预编译 JS bundle 加载。宿主从后端获取 `_manifest.json` 发现组件，通过 `import()` 动态加载。

### 5.0 前端组件构建（运行时安装必需）

运行时安装的插件（构建后通过 zip 或粘贴安装）需要将 `.vue` SFC 预编译为 JS bundle。

```bash
# 在项目根目录运行
node scripts/build-plugin-frontend.js ./plugins/my_plugin
```

这会将 `frontend/*.vue` 编译为 `frontend/dist/*.js`（自包含 bundle）并生成 `frontend/dist/_manifest.json`。

生成的 bundle 从宿主的 `window.__zaoWu_vue` 获取 Vue 实例，无需在插件中打包 Vue。

**限制：**
- 仅支持单文件组件（不自动跟踪子组件依赖链）
- `<script setup>` 中的 TypeScript 类型注解会被自动剥离
- 子组件 import 会被转为动态 import（需确保路径可访问）

### 5.1 组件发现机制

宿主扫描 `plugins/*/frontend/*.vue` 路径模式，按 `插件名:组件名` 注册到全局注册表。当后端钩子返回 `component: 'Panel'` 时，前端会查找 `plugins/your_plugin/frontend/Panel.vue` 并动态渲染。

### 5.2 侧栏面板 (Panel.vue)

当用户点击 ActivityBar 上对应的插件面板图标时，SidePanel 会渲染此组件。

```vue
<template>
  <div class="my-panel">
    <h3>{{ title }}</h3>
    <p>插件面板内容</p>
    <button @click="refresh">刷新</button>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const title = ref('我的插件')

async function refresh() {
  // 调用插件自定义的 HTTP API
  const res = await fetch('/api/plugins/my_plugin/hello')
  const data = await res.json()
  title.value = data.greeting
}

onMounted(() => refresh())
</script>
```

### 5.3 状态栏小部件 (StatusWidget.vue)

渲染在底部状态栏，适合显示简短的状态信息。

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

### 5.4 设置页面 (Settings.vue)

渲染在插件管理页面的设置区域，用于修改插件配置。

```vue
<template>
  <div class="my-settings">
    <div class="setting-row">
      <label>城市名称</label>
      <input v-model="city" @change="save" />
    </div>
    <div v-if="saved" class="saved-msg">已保存</div>
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

### 5.5 插件详情页分区 (DetailSection.vue)

渲染在插件管理详情页中（日志区域之后），适合展示插件相关的附加信息，例如 README、运行状态、统计图表等。宿主会自动将多个插件返回的分区按 `order` 排序并渲染。

```vue
<template>
  <div class="my-detail-section">
    <p>插件详情页扩展内容</p>
    <button @click="refresh">刷新</button>
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

### 5.6 可用的 lucide 图标

ActivityBar 和设置页面使用的图标来自 [lucide](https://lucide.dev)，宿主预导入了以下图标供插件使用：

`MessageSquare` `FolderTree` `Search` `GitBranch` `Puzzle` `Users` `Settings` `Zap` `Smile` `Bell` `Star` `Heart` `AlertCircle`

如果插件声明了未预导入的图标名，会自动降级为 `Puzzle` 图标。

### 5.6 CSS 变量

插件组件应使用宿主提供的 CSS 变量以保持主题一致性：

| 变量 | 用途 |
|------|------|
| `var(--text-primary)` | 主要文字颜色 |
| `var(--text-secondary)` | 次要文字颜色 |
| `var(--text-tertiary)` | 辅助文字颜色 |
| `var(--bg-primary)` | 主背景色 |
| `var(--bg-secondary)` | 次背景色 |
| `var(--bg-glass)` | 玻璃态背景 |
| `var(--bg-glass-hover)` | 玻璃态悬停背景 |
| `var(--bg-glass-active)` | 玻璃态激活背景 |
| `var(--border-subtle)` | 边框色 |
| `var(--border-glass)` | 玻璃态边框色 |
| `var(--accent)` | 强调色 |
| `var(--accent-hover)` | 强调色悬停 |
| `var(--accent-muted)` | 淡强调色 |
| `var(--success)` | 成功色 |
| `var(--danger)` | 危险/错误色 |
| `var(--transition)` | 过渡动画 |

---

## 6. plugin_api 服务接口

`plugin_api` 是插件访问宿主服务的唯一入口。它是一个进程级单例，在钩子函数内部通过 ContextVar 自动绑定当前插件的上下文（config、logger、name）。

### 6.1 导入方式

```python
from plugin_system.api import plugin_api
```

### 6.2 属性（仅在钩子函数内可用）

| 属性 | 类型 | 说明 |
|------|------|------|
| `plugin_api.name` | `str` | 当前插件名称 |
| `plugin_api.config` | `dict` | 当前插件的合并配置（清单默认值 + 用户修改值） |
| `plugin_api.logger` | `Logger` | 命名空间为 `plugin.<name>` 的标准库 logger |

> ⚠️ 这三个属性通过 ContextVar 实现，**只能在钩子函数调用期间访问**。如果在模块顶层或其他非钩子上下文中使用，会抛出 `RuntimeError`。如需在回调中使用，请在钩子内捕获到变量中。

### 6.3 方法

| 方法 | 说明 |
|------|------|
| `plugin_api.get_projects()` | 获取所有已注册项目列表，返回 `list[dict]`，每个 dict 含 `id`、`path` 等字段 |
| `plugin_api.get_setting(key, default)` | 读取宿主 `settings.json` 中的配置项，`default` 为未找到时的返回值 |
| `plugin_api.get_app()` | 获取 Quart 应用实例（高级用法） |
| `plugin_api.get_room_service()` | 获取协作房间服务模块 |
| `plugin_api.broadcast_to_room(room_id, payload)` | 向协作房间广播自定义 JSON 消息（async） |
| `plugin_api.register_blueprint(bp, url_prefix)` | 注册 Quart Blueprint（在 `zaowu_register_routes` 钩子中使用） |
| `plugin_api.start_subprocess(*args, **kwargs)` | 启动子进程，宿主会在插件禁用/关闭时自动终止它 |

### 6.4 使用示例

```python
from plugin_system.api import plugin_api

def zaowu_app_startup():
    # 读取配置
    city = plugin_api.config.get('city', 'Beijing')
    plugin_api.logger.info('monitoring weather for %s', city)

    # 读取宿主设置
    theme = plugin_api.get_setting('theme', 'dark')

    # 获取项目列表
    projects = plugin_api.get_projects()
    plugin_api.logger.info('found %d projects', len(projects))

async def zaowu_on_file_saved(path):
    # 向协作房间广播文件保存事件
    await plugin_api.broadcast_to_room('main', {
        'type': 'plugin.file_saved',
        'payload': {'path': path},
    })
```

---

## 7. event_bus 插件间通信

`event_bus` 是一个进程内的发布/订阅总线，用于**插件之间的横向通信**。宿主本身不使用这个总线。

### 7.1 导入方式

```python
from plugin_system.bus import event_bus
```

### 7.2 API

| 方法 | 说明 |
|------|------|
| `event_bus.subscribe(event_name, handler, owner)` | 订阅事件。`handler` 可以是普通函数或 async 函数。`owner` 传插件名（默认 `'?'`），用于禁用时自动清理 |
| `event_bus.unsubscribe(event_name, handler)` | 取消单个订阅 |
| `event_bus.unsubscribe_all(owner)` | 取消某个插件的所有订阅 |
| `event_bus.publish(event_name, payload)` | 发布事件。同步 handler 内联执行，异步 handler 调度到事件循环 |
| `event_bus.publish_async(event_name, payload)` | 异步发布，会 await 所有异步 handler 完成 |

### 7.3 使用示例

```python
# 插件 A：发布事件
from plugin_system.bus import event_bus

def zaowu_app_startup():
    event_bus.publish('weather.updated', {
        'city': 'Beijing',
        'temp': 25,
    })


# 插件 B：订阅事件
from plugin_system.bus import event_bus

def _on_weather_updated(payload):
    print(f"Weather: {payload['city']} {payload['temp']}°C")

def zaowu_app_startup():
    event_bus.subscribe('weather.updated', _on_weather_updated, owner='my_plugin')

def zaowu_app_shutdown():
    event_bus.unsubscribe_all('my_plugin')
```

> **提示：** 虽然宿主会在插件禁用时自动调用 `unsubscribe_all`，但建议在 `zaowu_app_shutdown` 中显式清理以保持良好习惯。

---

## 8. 前端事件总线 pluginEventBus

当用户点击 ActivityBar 上的插件按钮时，宿主通过前端事件总线派发事件。插件的前端代码可以监听这些事件。

### 8.1 工作原理

1. 插件在 `zaowu_activity_bar_actions()` 中声明 `handler: 'my_plugin.click'`
2. 用户点击该按钮
3. 宿主调用 `pluginEventBus.emit('my_plugin.click', {...})`
4. 插件前端组件通过 `pluginEventBus.on('my_plugin.click', callback)` 响应

### 8.2 前端用法

```vue
<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { pluginEventBus } from '@/plugin-system/events'

function handleClick(payload: any) {
  console.log('Button clicked!', payload)
  // 执行你的逻辑...
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

| 方法 | 说明 |
|------|------|
| `pluginEventBus.on(event, handler)` | 监听事件 |
| `pluginEventBus.off(event, handler)` | 移除监听 |
| `pluginEventBus.emit(event, payload?)` | 触发事件 |

---

## 9. 配置系统

### 9.1 配置的来源与合并

插件配置有两个来源，运行时自动合并：

1. **清单默认值** — `manifest.json` 中的 `config` 字段
2. **用户修改值** — 用户通过设置页面或 API 修改的值，持久化在 `plugins/.plugin_state.json`

合并规则：用户修改值覆盖清单默认值。在钩子函数中通过 `plugin_api.config` 访问合并后的结果。

### 9.2 读取配置

```python
def zaowu_app_startup():
    cfg = plugin_api.config
    city = cfg.get('city', 'Beijing')       # 有默认值兜底
    unit = cfg.get('unit', 'celsius')
    interval = cfg.get('refreshInterval', 300)
    plugin_api.logger.info('city=%s unit=%s interval=%d', city, unit, interval)
```

### 9.3 前端修改配置

通过 `usePluginsStore` 的 `updateConfig` 方法：

```typescript
import { usePluginsStore } from '@/stores/plugins'

const pluginsStore = usePluginsStore()
await pluginsStore.updateConfig('my_plugin', {
  city: 'Shanghai',
  unit: 'fahrenheit',
})
```

---

## 10. WebSocket 消息扩展

插件可以注册自定义 WebSocket 消息类型，实现实时双向通信。

### 10.1 流程

1. 插件通过 `zaowu_ws_message_types()` 声明它处理哪些消息类型
2. 当前端发送匹配类型的 WS 消息时，宿主调用 `zaowu_handle_ws_message(msg_type, payload)`
3. 如果处理函数返回一个 dict，宿主会将其广播给房间内所有客户端

### 10.2 完整示例

```python
def zaowu_ws_message_types():
    """声明本插件处理的 WS 消息类型。"""
    return ['my_plugin.query']

def zaowu_handle_ws_message(msg_type, payload):
    """处理 WS 消息。返回 dict 广播，返回 None 不广播。"""
    if msg_type == 'my_plugin.query':
        result = do_something(payload)
        return {
            'type': 'my_plugin.result',
            'payload': result,
        }
    return None
```

> **🔒 Token 传递安全**
>
> 协作房间的 WebSocket 连接需要 token 认证。宿主支持两种 token 传递方式：
>
> 1. **`Sec-WebSocket-Protocol` 子协议（推荐）** — token 不进入 URL，不会泄露到访问日志：
>    ```javascript
>    // 前端连接时通过子协议传递 token
>    const ws = new WebSocket(wsUrl, ['auth.' + token])
>    ```
> 2. **URL query 参数（向后兼容）** — `?token=xxx`，会记录在访问日志/Referer 中，**已弃用**
>
> 服务端 `on_connect` 会优先从 `Sec-WebSocket-Protocol` 读取 token。插件如需自定义
> WS 认证逻辑，应遵循相同的安全原则：**避免在 URL 中传递敏感凭证**。
>
> 详见 [第 14 节：安全注意事项](#14-安全注意事项)。

---

## 11. 完整示例：天气插件

下面是一个功能完整的天气插件示例，综合运用了大部分插件能力。

### 目录结构

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
"""天气插件 — 演示完整的插件开发流程。"""

from plugin_system.api import plugin_api
from plugin_system.bus import event_bus


# ── 生命周期 ──────────────────────────────────────────────────────

def zaowu_plugin_loaded():
    plugin_api.logger.info('weather_widget loaded')


def zaowu_app_startup():
    city = plugin_api.config.get('city', 'Beijing')
    plugin_api.logger.info('monitoring weather for %s', city)
    # 发布事件，其他插件可以订阅
    event_bus.publish('weather.ready', {'city': city})


def zaowu_app_shutdown():
    event_bus.unsubscribe_all('weather_widget')
    plugin_api.logger.info('weather_widget shutdown')


# ── 文件事件 ──────────────────────────────────────────────────────

def zaowu_on_file_saved(path: str):
    plugin_api.logger.debug('file saved: %s', path)


# ── HTTP 路由 ─────────────────────────────────────────────────────

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


# ── 前端扩展 ─────────────────────────────────────────────────────

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
    <button @click="refresh" class="weather-btn">刷新</button>
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
      <label>城市 / City</label>
      <input v-model="city" @change="save" />
    </div>
    <div class="setting-row">
      <label>单位 / Unit</label>
      <select v-model="unit" @change="save">
        <option value="celsius">摄氏 °C</option>
        <option value="fahrenheit">华氏 °F</option>
      </select>
    </div>
    <div v-if="saved" class="saved-msg">已保存 / Saved</div>
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

## 12. 注意事项与常见问题

### 12.1 命名规则

- 插件目录名（即插件名）**仅允许英文字母、数字和下划线**，不支持中文、连字符或其他特殊字符。
- 前端组件文件名需与钩子函数中 `component` 字段值精确匹配（区分大小写）。

### 12.2 plugin_api 的作用域限制

`plugin_api.name`、`plugin_api.config`、`plugin_api.logger` 三个属性通过 Python 的 `contextvars.ContextVar` 实现，**只能在宿主调用钩子函数期间使用**。以下场景会抛出 `RuntimeError`：

```python
# ❌ 错误：在模块顶层访问
from plugin_system.api import plugin_api
print(plugin_api.config)  # RuntimeError!

# ❌ 错误：在异步回调中访问（已离开钩子调用栈）
async def zaowu_app_startup():
    async def callback():
        print(plugin_api.config)  # RuntimeError!
    asyncio.create_task(callback())

# ✅ 正确：在钩子内捕获到局部变量
async def zaowu_app_startup():
    cfg = dict(plugin_api.config)  # 捕获快照
    async def callback():
        print(cfg)  # OK
    asyncio.create_task(callback())
```

### 12.3 错误隔离

插件系统对每个钩子调用都做了 `try/except` 隔离。**一个插件抛出的异常不会影响宿主或其他插件。** 异常会被记录到日志中，插件开发者应关注 `plugin.<name>` 命名空间的日志输出。

### 12.4 钩子函数必须是同步或 async

钩子函数可以是普通函数或 `async def`，宿主会自动处理。但**不要在普通函数中使用 `await`**。

### 12.5 热重载

开发期间可以通过 API 调用 `POST /api/plugins/<name>/reload` 热重载插件，无需重启整个服务。插件的启用状态和用户配置会在重载后保留。

### 12.6 禁用与卸载

- **禁用** (`POST /api/plugins/<name>/disable`)：调用 `zaowu_plugin_disabled` 钩子，终止子进程，清理事件总线订阅。插件目录保留。
- **卸载** (`DELETE /api/plugins/<name>`)：先禁用，然后将插件目录重命名为 `<name>.disabled`（不会删除文件，方便恢复）。

### 12.7 子进程管理

通过 `plugin_api.start_subprocess()` 启动的子进程会被宿主追踪，在插件禁用或应用关闭时自动终止。**不要使用 `subprocess.Popen` 直接启动进程**，否则宿主无法追踪和清理。

### 12.8 路由注册的两种方式

`zaowu_register_routes` 钩子支持两种注册方式，宿主会同时处理：

1. **返回 Blueprint 列表**（推荐）— 宿主自动调用 `register_blueprint`
2. **在钩子内手动调用 `plugin_api.register_blueprint()`** — 适用于需要动态前缀的场景

### 12.9 前端组件的双轨加载

前端组件采用双轨加载机制：

- **构建时存在的插件**：通过 Vite 的 `import.meta.glob` 自动发现 `.vue` 源码，打包进主应用。
- **运行时安装的插件**：通过后端 API 获取 `_manifest.json`，动态 `import()` 加载 `frontend/dist/` 中的预编译 JS bundle。

这意味着：
- 构建时已有的插件可以直接使用 `.vue` 源码，无需额外构建步骤。
- 构建后安装的插件**必须包含 `frontend/dist/` 目录**（通过 `scripts/build-plugin-frontend.js` 生成）。
- 组件路径必须匹配 `plugins/*/frontend/*.vue`（构建时）或 `plugins/*/frontend/dist/*.js`（运行时）。
- 组件以异步组件方式加载（`defineAsyncComponent`），不会阻塞首屏。

### 12.10 配置持久化

用户修改的配置保存在 `plugins/.plugin_state.json` 中，格式为：

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

手动编辑此文件后重启服务即可生效。

### 12.11 插件安装方式

插件支持以下两种安装方式：

**方式一：手动粘贴（开发阶段 / 目录模式构建）**

将插件目录直接复制到 `plugins/` 文件夹中，然后：
- 重启应用，或
- 调用 `POST /api/plugins/discover` 重新扫描

> ⚠️ **PyInstaller 单文件模式**下，`plugins/` 位于系统临时目录，重启后手动粘贴的插件会丢失。请使用 zip 安装 API 或使用目录模式构建。

**方式二：zip 安装 API（推荐，适用于所有构建模式）**

```bash
# 将插件目录打包为 zip
cd plugins/my_plugin && zip -r ../../my_plugin.zip . && cd ../..

# 通过 API 安装
curl -X POST http://localhost:5000/api/plugins/install \
  -F "file=@my_plugin.zip"
```

前端 UI 也提供了一键安装按钮（插件管理面板顶部的上传图标），支持选择 `.zip` 文件安装。

**打包要求：**
- zip 内可直接包含插件文件，也可嵌套一层目录
- 必须包含 `manifest.json` 和 `__init__.py`
- 前端组件需要预编译：先运行 `node scripts/build-plugin-frontend.js ./plugins/my_plugin`，再打包

---

## 13. 插件 API 能力速查表

### 后端能力

| 能力 | 接口/钩子 | 说明 |
|------|-----------|------|
| 读取自身配置 | `plugin_api.config` | 合并后的配置字典 |
| 写日志 | `plugin_api.logger.info/warning/error(...)` | 命名空间 `plugin.<name>` |
| 获取项目列表 | `plugin_api.get_projects()` | 等价于 `/api/explorer/projects` |
| 读宿主设置 | `plugin_api.get_setting(key, default)` | 读取 `settings.json`，`default` 为默认值 |
| 注册 HTTP 路由 | `zaowu_register_routes()` + `plugin_api.register_blueprint()` | 需在 Blueprint 中设置 `url_prefix='/api/plugins/<name>'` |
| 注册前端面板 | `zaowu_sidebar_panels()` | 侧栏面板 |
| 注册工具栏按钮 | `zaowu_activity_bar_actions()` | ActivityBar 图标按钮 |
| 注册设置区域 | `zaowu_settings_sections()` | 设置页面分区 |
| 注册状态栏项 | `zaowu_status_bar_items()` | 底部状态栏 |
| 注册插件详情页分区 | `zaowu_plugin_detail_sections()` | 插件管理详情页分区 |
| 插件间通信 | `event_bus.subscribe/publish` | 进程内事件总线 |
| WebSocket 消息 | `zaowu_ws_message_types()` + `zaowu_handle_ws_message()` | 实时双向通信 |
| 广播到房间 | `await plugin_api.broadcast_to_room(room_id, payload)` | 协作房间广播 |
| 启动子进程 | `plugin_api.start_subprocess(...)` | 自动追踪和清理 |
| 获取 Quart 应用 | `plugin_api.get_app()` | 高级用法 |

### 前端能力

| 能力 | 接口 | 说明 |
|------|------|------|
| 监听插件按钮点击 | `pluginEventBus.on(event, handler)` | ActivityBar 按钮事件 |
| 读取插件配置 | `usePluginsStore().fetchPlugins()` | Pinia store |
| 修改插件配置 | `usePluginsStore().updateConfig(name, config)` | 持久化到服务端 |
| 使用宿主 CSS 变量 | `var(--text-primary)` 等 | 自动适配明暗主题 |

---

## 14. 安全注意事项

插件运行在宿主进程中，拥有与宿主相同的系统权限。**安全漏洞不仅影响插件本身，还可能危及整个宿主应用和用户系统。** 本节列出插件开发必须遵循的安全准则。

### 14.1 输入校验 — 所有外部输入都不可信

**规则：** 插件路由接收的所有 `request.get_json()` 输入都必须经过类型和内容校验，禁止直接 `data.get('key', '')` 取值后使用。

**使用 `services/input_validation.py` 工具（推荐）：**

```python
from services.input_validation import (
    require_str,        # 必填字符串校验
    get_str,            # 可选字符串校验
    require_path,       # 路径校验（防 null 字节注入）
    require_command,    # 命令校验（防 CRLF 注入）
    require_int,        # 整数校验（含范围限制）
    validate_json_body, # 请求体校验
)

@bp.route('/process', methods=['POST'])
async def process():
    data = await request.get_json(silent=True)

    # 1. 校验请求体是有效 JSON 对象
    ok, err = validate_json_body(data)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400

    # 2. 校验必填字符串字段（含长度限制）
    ok, err = require_str(data, 'name', max_len=100)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400

    # 3. 校验路径字段（防止 null 字节注入）
    ok, err = require_path(data, 'target_path')
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400

    # 4. 校验可选整数字段（含范围限制）
    ok, err, count = require_int(data, 'count', min_val=1, max_val=1000)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400

    # 安全使用已校验的字段
    return jsonify({'ok': True, 'name': data['name']})
```

**校验工具说明：**

| 函数 | 用途 | 安全检查 |
|------|------|----------|
| `require_str(data, key, max_len)` | 必填字符串 | 类型检查、非空、长度限制 |
| `get_str(data, key, default, max_len)` | 可选字符串 | 同上，缺失返回默认值 |
| `require_path(data, key, max_len=4096)` | 文件路径 | 同上 + null 字节检测 |
| `require_command(data, key, max_len=2000)` | 命令字符串 | 同上 + CRLF 控制字符检测 |
| `require_int(data, key, min_val, max_val)` | 整数 | 类型转换 + 范围限制 |
| `validate_json_body(data)` | 请求体 | 非空 dict 校验 |

> **注意：** 路径遍历（`../`）的防护由宿主的 `is_path_in_projects()` 负责，插件应调用该函数或 `plugin_api.get_projects()` 确保路径在合法项目范围内。

### 14.2 命令执行安全

**规则：** 插件如需执行系统命令，**必须**使用宿主提供的安全校验机制，禁止直接 `subprocess.run(command, shell=True)`。

**安全执行方式（按推荐顺序）：**

```python
# 方式一：使用 services/terminal_utils.py（推荐，已封装安全校验）
from services.terminal_utils import agent_is_command_safe, execute_command

def zaowu_register_routes():
    from quart import Blueprint, jsonify, request

    bp = Blueprint('my_plugin', __name__, url_prefix='/api/plugins/my_plugin')

    @bp.route('/run', methods=['POST'])
    async def run():
        data = await request.get_json(silent=True)
        command = data.get('command', '')

        # 安全校验：白名单 + shell 操作符检测
        safe, err = agent_is_command_safe(command)
        if not safe:
            return jsonify({'ok': False, 'error': err}), 400

        # 安全执行（异步，自动超时）
        result = await execute_command(command, cwd='/project/path')
        return jsonify(result)

    return [bp]
```

**禁止的做法：**

```python
# ❌ 危险：shell=True + 无校验，可被命令注入攻击
subprocess.run(user_input, shell=True)

# ❌ 危险：即使有白名单，不检测 shell 操作符也可被绕过
# 攻击示例：'git status && rm -rf /'
cmd_parts = user_input.split()
if cmd_parts[0] in ALLOWED:
    subprocess.run(user_input, shell=True)  # 仍可被 && | ; 绕过
```

**`agent_is_command_safe` 提供的防护：**
1. **黑名单子串检查** — 拦截 `rm -rf`、`format`、`shutdown` 等危险命令
2. **Shell 操作符检测** — 拒绝 `|`、`&&`、`||`、`;`、反引号、`$()`，防止命令链接
3. **白名单检查** — 使用 `shlex.split` 正确解析，校验首词

### 14.3 路径安全

**规则：** 所有文件系统操作必须验证路径在合法项目范围内，防止路径遍历攻击。

```python
import os
from routes.explorer import is_path_in_projects

def safe_file_read(path: str) -> str:
    """安全读取文件 — 路径必须在已注册项目内。"""
    real = os.path.realpath(path)
    if not is_path_in_projects(real):
        raise PermissionError(f'path outside project scope: {path}')
    with open(real, 'r', encoding='utf-8') as f:
        return f.read()
```

**防护要点：**
- 使用 `os.path.realpath()` 解析符号链接和 `..`
- 调用 `is_path_in_projects()` 确保路径在已注册项目内
- 拒绝包含 null 字节（`\x00`）的路径（使用 `require_path` 校验）

### 14.4 Token 与认证

**规则：** 协作房间的 WebSocket token 不应通过 URL query 参数传递（会泄露到访问日志/Referer）。

**推荐的 token 传递方式：**

```javascript
// 前端：通过 Sec-WebSocket-Protocol 子协议传递 token
const ws = new WebSocket(wsUrl, ['auth.' + token])
```

```python
# 后端：服务端 on_connect 会优先从 Sec-WebSocket-Protocol 读取 token
# 插件如需自定义认证，应遵循相同原则
```

**REST 接口的 token 传递：**

```python
# ✅ 推荐：通过 Authorization 头
@bp.route('/protected', methods=['GET'])
async def protected():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    token = auth[7:]

# ❌ 危险：通过 URL query 参数（会泄露到日志）
@bp.route('/protected', methods=['GET'])
async def protected():
    token = request.args.get('token', '')  # 会记录在访问日志中！
```

### 14.5 CORS 与跨域防护

宿主已配置 Origin 白名单中间件，仅允许本地来源（`127.0.0.1`、`localhost`）的浏览器请求。这防止了恶意网页跨域调用本地 API。

**插件无需额外配置 CORS**，但应注意：
- 插件路由继承宿主的 CORS 防护
- 如插件需要允许特定外部来源，应通过 `zaowu_mount_asgi_middleware` 钩子谨慎添加
- **不要**在插件中移除或绕过宿主的 Origin 校验

### 14.6 敏感信息处理

**规则：** 禁止在代码或配置中硬编码 API Key、密码、token 等敏感信息。

```python
# ❌ 危险：硬编码密钥
API_KEY = 'sk-xxxxxxxxxxxx'

# ✅ 安全：从运行时配置读取（providers.json，已被 .gitignore 排除）
import json, os
from zaowu_paths import get_project_root

def load_api_key():
    config_path = os.path.join(get_project_root(), 'providers.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        providers = json.load(f).get('providers', [])
    # 用户在 UI 中配置，明文存储在 gitignored 文件中
    return providers[0].get('apiKey', '') if providers else ''
```

**安全检查清单：**
- [ ] 代码中无硬编码的 API Key / 密码 / token
- [ ] 敏感配置存储在 `.gitignore` 排除的文件中（`providers.json`、`settings.json`）
- [ ] 日志中不输出敏感信息（`plugin_api.logger.info(f'key={api_key}')` 是错误的）
- [ ] 错误响应中不泄露内部实现细节（如堆栈跟踪、SQL 语句）

### 14.7 SQL 安全

**规则：** 禁止用 f-string 或字符串拼接构造 SQL 语句，必须使用参数化查询。

```python
import aiosqlite

# ✅ 安全：参数化查询
async def get_user(db_path: str, user_id: str):
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            'SELECT * FROM users WHERE id = ?',
            (user_id,)  # 参数化
        )
        return await cursor.fetchone()

# ❌ 危险：f-string 拼接（SQL 注入风险）
await db.execute(f"SELECT * FROM users WHERE id = '{user_id}'")
```

### 14.8 安全自查清单

发布插件前，请逐项确认：

| 检查项 | 说明 |
|--------|------|
| 输入校验 | 所有 `request.get_json()` 输入已使用 `services/input_validation` 校验 |
| 命令执行 | 如有命令执行，使用 `agent_is_command_safe` 校验，无 `shell=True` 裸调用 |
| 路径安全 | 文件操作使用 `os.path.realpath` + `is_path_in_projects` 校验 |
| Token 安全 | WebSocket token 通过 `Sec-WebSocket-Protocol` 传递，REST token 通过 `Authorization` 头 |
| 无硬编码密钥 | 代码中无 API Key / 密码 / token 字面量 |
| SQL 参数化 | 数据库查询使用 `?` 占位符，无 f-string 拼接 |
| 日志安全 | 日志中不输出敏感信息 |
| 错误处理 | 异常捕获具体（非宽泛 `except Exception`），错误响应不泄露内部细节 |

---

## 附录：hello_world 示例插件

项目内置的 `plugins/hello_world/` 是一个参考实现，展示了生命周期、前端扩展（面板/活动栏/状态栏/设置）、HTTP 路由、WebSocket 消息、事件总线等核心能力的最小用法。开发新插件时可以复制它作为起点：

```bash
cp -r plugins/hello_world plugins/my_plugin
```

然后修改 `manifest.json` 中的 `name` 和 `__init__.py` 中的逻辑即可。

---

> 如有疑问，可参考 `plugins/PLUGIN_SYSTEM.md`（架构设计文档）或阅读 `plugin_system/` 目录下的源码。
