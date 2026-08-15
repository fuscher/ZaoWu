# ZaoWu

[English](README_EN.md) | **中文**

面向软件开发的 AI Agent 桌面应用。集对话、编码工具链、工作流编排与实时协作为一体，以本地优先的方式把 LLM 能力接入日常开发流程。

- 当前版本：`0.2.0` ｜ 协议：Apache-2.0

---

## 特性

| 能力 | 说明 |
| --- | --- |
| AI 对话与 Agent | 兼容 OpenAI 接口的 Provider 接入，流式输出、多轮对话、模型切换与生成参数调节；Agent 模式支持工具调用、沙箱执行与人工审批 |
| 工作流引擎 | 可视化编排 LLM、工具、条件、循环、子图等节点，SSE 实时推送执行过程 |
| 实时协作 | 基于 Yjs CRDT 的多端同步编辑，房间邀请制，主持人 / 协作者 / 观察者三级角色权限 |
| 代码工具链 | 项目资源管理器、全文搜索、Git 面板（变更、提交图、分支管理）、内置终端 |
| 插件系统 | Python 后端 + Vue 前端双层插件架构，事件总线与钩子机制，支持热加载与市场安装 |
| 技能模块 | 代码评审、重构、文档生成等技能包按需加载，与 Agent 工具链联动 |
| 更新与分发 | 双源版本检测、流式下载、Go 启动器实现版本无缝切换与失败回滚 |

## 架构

```
┌────────────────────────────────────────────────┐
│  ZaoWu.exe 桌面外壳（pywebview + WebView2）      │
├────────────────────────────────────────────────┤
│  Vue 3 · TypeScript · CodeMirror · Vue Flow    │
│  Pinia · Yjs（前端 / ZaoWu/dist）               │
├────────────── HTTP / SSE / WebSocket ──────────┤
│  Quart (ASGI) + Hypercorn 后端                  │
│  pycrdt · aiosqlite · GitPython                │
│  ┌──────────┬─────────┬───────────┬──────────┐ │
│  │ 对话/Agent │ 工作流引擎 │ 插件系统    │ 社区协作 │ │
│  │ 资源/搜索  │ Git/终端 │ 技能模块    │ 更新服务 │ │
│  └──────────┴─────────┴───────────┴──────────┘ │
├────────────────────────────────────────────────┤
│  ZaoWuLauncher（Go）— 版本切换 / 健康检查 / 回滚   │
└────────────────────────────────────────────────┘
```

## 技术栈

| 层 | 技术 |
| --- | --- |
| 桌面外壳 | pywebview（WebView2）、自定义无边框窗口 |
| 前端 | Vue 3、TypeScript、Vite、Pinia、CodeMirror 6、Vue Flow、Yjs |
| 后端 | Python 3.12、Quart、Hypercorn、pycrdt、aiosqlite |
| 协作同步 | Yjs / y-websocket / pycrdt-websocket（CRDT 实时协同） |
| 更新器 | Go 编写的独立启动器，负责版本切换、健康检查与回滚 |
| 打包 | PyInstaller（`tobuild/build.bat`），产物为单目录 Windows 包 |

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 22.18+ / 24.12+

### 启动

```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 构建前端（后端直接托管 dist 产物）
cd ZaoWu
npm install
npm run build
cd ..

# 3. 启动应用
python main.py
```

### 开发模式

```bash
# 后端（提供 127.0.0.1:5000 全部 API）
python main.py

# 前端热更新（代码改动即时生效，构建后经后端访问）
cd ZaoWu && npm run dev
```

### 测试

```bash
# 后端（约 40 个测试模块，覆盖路由、安全、工作流、插件等）
pytest

# 前端单元测试
cd ZaoWu && npm run test:unit
```

### 打包发布

```bash
tobuild\build.bat
```

产出 `dist/ZaoWu-{version}-win64.zip` 与 `dist/version.json`（含 SHA256 与体积，供更新服务校验）。

## 目录结构

```
├── main.py                  # 桌面入口：启动后端 + pywebview 窗口
├── server_quart.py          # Quart ASGI 应用，注册全部 API 蓝图
├── zaowu_paths.py           # 开发 / frozen 双环境路径解析
├── version.py               # 版本号单一来源与更新判定
├── routes/                  # API 蓝图（explorer / search / git / chat / workflow / ...）
├── services/                # 业务层（对话存储、工具执行、权限、技能、协作房间）
├── workflow_engine/         # 工作流执行引擎（节点注册、SSE 输出）
├── agent_modules/           # Agent 核心与技能包（code_review / refactor / doc_generate）
├── plugin_system/           # 插件框架（加载器、事件总线、钩子、Schema）
├── plugins/                 # 内置插件（含插件开发指南）
├── community_ws.py          # 社区协作 WebSocket 服务
├── launcher/                # Go 启动器（版本切换、健康检查、回滚）
├── tobuild/                 # 打包脚本与 PyInstaller spec
├── ZaoWu/                   # Vue 3 前端工程
└── tests/                   # pytest 测试套件
```

## 文档

- `plugins/PLUGIN_DEV_GUIDE.md` — 插件开发指南（含英文版）

## License

[Apache License 2.0](LICENSE)