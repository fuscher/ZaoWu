# ZaoWu

**English** | [中文](README.md)

A desktop AI Agent application for software development. It combines chat, coding toolchains, workflow orchestration, and real-time collaboration, bringing LLM capabilities into everyday development flows in a local-first way.

- Current version: `0.3.0` ｜ License: Apache-2.0

---

## Features

| Capability | Description |
| --- | --- |
| AI Chat & Agent | OpenAI-compatible provider support with streaming output, multi-turn conversations, model switching, and tunable generation parameters; Agent mode supports tool calling, sandboxed execution, and human approval; supports @ file/project citation and project sandbox, with citations truncated by token and counted into the context-compression budget |
| Workflow Engine | Visually orchestrate LLM, tool, condition, loop, and subgraph nodes; SSE pushes real-time execution progress |
| Real-time Collaboration | Multi-client synchronized editing based on Yjs CRDT, invite-based rooms with host / collaborator / observer role permissions |
| Coding Toolchain | Project explorer, full-text search, Git panel (changes, commit graph, branch management), built-in terminal |
| Plugin System | Dual-layer plugin architecture (Python backend + Vue frontend) with event bus and hooks, hot-reload and marketplace installation |
| Skills Module | Code review, refactoring, doc generation and other skill packages loaded on demand, integrated with the Agent toolchain |
| Updates & Distribution | Three-source version detection, streaming download, Go launcher for seamless version switching with rollback on failure |

## Architecture

```
┌────────────────────────────────────────────────┐
│ ZaoWu.exe Desktop shell (pywebview + WebView2) │
├────────────────────────────────────────────────┤
│  Vue 3 · TypeScript · CodeMirror · Vue Flow    │
│  Pinia · Yjs (frontend / ZaoWu/dist)           │
├────────────── HTTP / SSE / WebSocket ──────────┤
│  Quart (ASGI) + Hypercorn backend              │
│  pycrdt · aiosqlite · GitPython                │
│  ┌─────────┬──────────┬──────────┬───────────┐ │
│  │ Agent   │ Workflow │ Plugins  │ Community │ │
│  │ Search  │ Git/Term │ Skills   │ Updater   │ │
│  └─────────┴──────────┴──────────┴───────────┘ │
├────────────────────────────────────────────────┤
│  ZaoWuLauncher (Go) — version / rollback       │
└────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
| --- | --- |
| Desktop shell | pywebview (WebView2), custom frameless window |
| Frontend | Vue 3, TypeScript, Vite, Pinia, CodeMirror 6, Vue Flow, Yjs |
| Backend | Python 3.12, Quart, Hypercorn, pycrdt, aiosqlite |
| Collaboration | Yjs / y-websocket / pycrdt-websocket (CRDT real-time sync) |
| Updater | Standalone Go launcher handling version switching, health checks, and rollback |
| Packaging | PyInstaller (`tobuild/build.bat`), single-directory Windows package |

## Quick Start

### Requirements

- Python 3.12+
- Node.js 22.18+ / 24.12+

### Launch

```bash
# 1. Install backend dependencies
pip install -r requirements.txt

# 2. Build the frontend (the backend serves the dist output directly)
cd ZaoWu
npm install
npm run build
cd ..

# 3. Start the application
python main.py
```

### Development mode

```bash
# Backend (serves all APIs at 127.0.0.1:5000)
python main.py

# Frontend hot reload (changes apply immediately; accessed through the backend after building)
cd ZaoWu && npm run dev
```

### Tests

```bash
# Backend (~40 test modules covering routes, security, workflows, plugins, etc.)
pytest

# Frontend unit tests
cd ZaoWu && npm run test:unit
```

### Packaging & release

```bash
tobuild\build.bat
```

Produces `dist/ZaoWu-{version}-win64.zip` and `dist/version.json` (with SHA256 and size, for the update service to verify).

## Directory Structure

```
├── main.py                  # Desktop entry: starts the backend + pywebview window
├── server_quart.py          # Quart ASGI app, registers all API blueprints
├── zaowu_paths.py           # Path resolution for dev / frozen environments
├── version.py               # Single source of the version number and update checks
├── routes/                  # API blueprints (explorer / search / git / chat / workflow / ...)
├── services/                # Business layer (conversation store, tool execution, permissions, skills, rooms)
├── workflow_engine/         # Workflow engine (node registry, SSE output)
├── agent_modules/           # Agent core and skill packages (code_review / refactor / doc_generate)
├── plugin_system/           # Plugin framework (loader, event bus, hooks, schema)
├── plugins/                 # Built-in plugins (includes the plugin development guide)
├── community_ws.py          # Community collaboration WebSocket service
├── launcher/                # Go launcher (version switch, health check, rollback)
├── tobuild/                 # Packaging scripts and PyInstaller spec
├── ZaoWu/                   # Vue 3 frontend project
└── tests/                   # pytest test suite
```

## Documentation

- `plugins/PLUGIN_DEV_GUIDE.md` — plugin development guide (English version included)

## License

[Apache License 2.0](LICENSE)
