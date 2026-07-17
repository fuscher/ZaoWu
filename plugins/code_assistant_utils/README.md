# code_assistant_utils

为 ZaoWu 智能体（Agent）模块提供一组**只读、安全、高频使用**的代码助手工具。本插件严格通过 `zaowu_register_agent_tools` 扩展点注册工具，不修改、不侵入主程序的核心业务逻辑。

---

## 目录

1. [功能概述](#1-功能概述)
2. [安装与启用](#2-安装与启用)
3. [提供的智能体工具](#3-提供的智能体工具)
4. [配置项](#4-配置项)
5. [主题与样式](#5-主题与样式)
6. [开发与调试](#6-开发与调试)
7. [测试](#7-测试)
8. [兼容性说明](#8-兼容性说明)

---

## 1. 功能概述

`code_assistant_utils` 是一个后端驱动的 Agent 工具插件，补充了核心工具集未覆盖的常见开发辅助能力：

- 获取当前时间/时间戳
- 统计项目或文件的代码行数
- 批量生成 UUID
- 格式化/校验 JSON

所有工具均为只读操作，不需要用户二次确认，适合在智能体循环中高频调用。

---

## 2. 安装与启用

本插件采用文件夹部署方式，符合 ZaoWu 插件系统规范。

### 2.1 目录结构

```text
plugins/
└── code_assistant_utils/
    ├── manifest.json          # 插件清单
    ├── __init__.py            # 后端入口与工具注册
    ├── frontend/
    │   └── Settings.vue       # 设置页面（可选）
    └── README.md              # 本文件
```

### 2.2 启用插件

将本目录复制到 ZaoWu 项目的 `plugins/` 文件夹下，重启服务即可自动加载。

如需禁用或配置：

```bash
# 禁用
POST /api/plugins/code_assistant_utils/disable

# 启用
POST /api/plugins/code_assistant_utils/enable

# 热重载（开发时）
POST /api/plugins/code_assistant_utils/reload
```

---

## 3. 提供的智能体工具

智能体通过标准 OpenAI 函数调用方式使用这些工具。

### 3.1 `get_current_time`

获取当前时间信息。

**参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tz_name` | `string` | 否 | `'local'`（默认）或 `'utc'` |

**返回值示例：**

```json
{
  "ok": true,
  "iso": "2026-07-16T14:30:00",
  "date": "2026-07-16",
  "time": "14:30:00",
  "timezone": "CST",
  "timestamp": 1752661800
}
```

### 3.2 `count_code_lines`

统计指定文件或目录的代码行数、空行数、注释行数。

**参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | `string` | 是 | 文件或目录的绝对路径 |
| `exclude_patterns` | `array<string>` | 否 | 要排除的目录名列表 |

**特性：**

- 自动识别并跳过二进制文件
- 默认排除 `node_modules`、`.git`、`__pycache__`、`.venv`、`venv`、`dist`、`build`
- 可通过插件配置或调用参数自定义排除规则

**返回值示例：**

```json
{
  "ok": true,
  "path": "D:/Git/ZaoWu/services",
  "files": 12,
  "total_lines": 856,
  "blank_lines": 98,
  "code_lines": 652,
  "comment_lines": 106
}
```

### 3.3 `generate_uuid`

生成一个或多个 UUID v4。

**参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `count` | `integer` | 否 | 生成数量，默认 `1`，最大 `10` |

**返回值示例：**

```json
{
  "ok": true,
  "count": 3,
  "uuids": [
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "...",
    "..."
  ]
}
```

### 3.4 `format_json`

格式化或校验 JSON 字符串。

**参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `content` | `string` | 是 | 待格式化的 JSON 字符串 |
| `indent` | `integer` | 否 | 缩进空格数，默认 `2`，范围 `1-8` |

**返回值示例：**

```json
{
  "ok": true,
  "formatted": "{\n  \"a\": 1\n}",
  "is_valid": true
}
```

---

## 4. 配置项

可在插件设置页面修改，或直接调用 API：

```bash
POST /api/plugins/code_assistant_utils/config
Content-Type: application/json

{
  "default_timezone": "utc",
  "default_exclude_patterns": ["node_modules", ".git", "__pycache__"]
}
```

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `default_timezone` | `string` | `local` | `get_current_time` 的默认时区 |
| `default_exclude_patterns` | `array<string>` | 见 `manifest.json` | `count_code_lines` 的默认排除目录 |

---

## 5. 主题与样式

前端设置页面 `frontend/Settings.vue` 完全使用宿主提供的 CSS 变量，自动适配明暗主题：

- `var(--text-primary)` / `var(--text-secondary)` / `var(--text-tertiary)`
- `var(--bg-primary)` / `var(--bg-secondary)` / `var(--bg-glass)`
- `var(--border-subtle)` / `var(--border-glass)`
- `var(--accent)` / `var(--success)`
- `var(--transition)`

界面文本采用中英双语并列，符合 ZaoWu 国际化风格。

---

## 6. 开发与调试

### 6.1 日志

插件日志使用 `plugin.code_assistant_utils` 命名空间。启动服务后可在终端看到：

```text
plugin.code_assistant_utils: code_assistant_utils loaded (v1.0.0)
plugin.code_assistant_utils: code_assistant_utils ready: timezone=local, excludes=8 patterns
```

### 6.2 热重载

修改 `__init__.py` 后，调用 `POST /api/plugins/code_assistant_utils/reload` 即可生效，无需重启整个服务。

---

## 7. 测试

插件配套测试位于：

```text
tests/test_plugin_code_assistant_utils.py
```

运行方式：

```bash
# 仅运行本插件测试
python -m pytest tests/test_plugin_code_assistant_utils.py -v

# 运行全部测试，验证兼容性
python -m pytest tests/ -v
```

### 7.1 测试结果

- 插件专属测试：**18 / 18 通过**
- 全量回归测试：**110 / 110 通过**
- 未发现对主程序功能或性能的影响

---

## 8. 兼容性说明

- **最低插件 API 版本**：`1.0.0`
- **依赖的宿主扩展点**：`zaowu_register_agent_tools`
- **不依赖**：`zaowu_register_routes`、`zaowu_sidebar_panels` 等可选钩子
- **无副作用**：不创建子进程、不注册 WebSocket 消息类型、不修改宿主设置
- **线程安全**：所有工具函数均为无状态纯函数，可在智能体异步循环中安全调用

---

> 如需扩展更多工具，只需在 `__init__.py` 的 `zaowu_register_agent_tools()` 返回列表中追加新的 `ToolDefinition` 即可，无需改动主程序。
