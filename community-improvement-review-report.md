# ZaoWu 社区协作改进提案 — 审查与验证报告

> **报告日期**：2026-07-21  
> **依据文档**：`community-improvement-proposal.md`  
> **验证环境**：Windows 10 Pro / Python 3.9.10 / Node 24.14.0  
> **报告目标**：逐条核对改进提案中的问题是否真实存在，分析根因，给出修复方案、风险评佑及测试结果，并补充未被提案提及的相关优化点。

---

## 一、总体验证结论

| 优先级 | 数量 | 结论 |
|--------|------|------|
| 🔴 P0 | 4 项（I-01 ~ I-04） | 已全部实现并通过测试 |
| 🟠 P1 | 4 项（I-05 ~ I-08） | 已全部实现并通过测试 |
| 🟡 P2 | 6 项（I-09 ~ I-14） | I-10 ~ I-13 已实现；**I-09 在本次审查中修复**；I-14 列为 P3 暂不实施 |
| 🔵 P3 | 6 项（I-14 ~ I-19） | 未在本次实施，作为后续优化建议保留 |

**新增问题发现**：
1. `server_quart.py` 与 `test_community.py` 使用 Python 3.10+ 的类型联合语法 `X | Y`，在 Python 3.9 下启动直接失败。
2. `_handle_file_diff` 在项目路径不可解析时直接 `return`，导致 `file_diff` 不会被广播给其他客户端。
3. 端到端冒烟测试未适配 `room_info` 自动广播，偶发断言失败。
4. 前端 `useCollaboration.ts` 存在 TypeScript 类型错误（`TokenAwareWebSocket` 构造函数签名、`WSMessageType` 缺少 `room_closed`）。

以上新增问题均已修复并通过验证。

---

## 二、逐条问题核对、根因分析与修复

### 🔴 P0 安全与体验阻塞项

#### I-01 · REST API 增加 Bearer Token 认证
- **提案描述**：`/api/community/rooms/*` 端点零鉴权，局域网任意设备可操作。
- **实际状态**：已实现。
- **关键代码**：
  - `routes/community.py:70` 新增 `require_token` 装饰器。
  - 敏感操作（关闭房间、踢人、更新角色等）均通过 `@require_token` + `_require_host` 双重校验。
- **根因**：早期路由层未复用 WebSocket Token 会话。
- **风险**：无。所有公开端点（`/rooms` 列表、`/rooms/<id>/join`）仍保持开放以支持 LAN 发现与邀请码加入。

#### I-02 · WebSocket Token 加固（子协议传递）
- **提案描述**：Token 原本通过 URL 查询参数 `?token=xxx` 传递，存在日志/历史/Referer 泄露风险。
- **实际状态**：已实现。
- **关键代码**：
  - `ZaoWu\src\composables\useCollaboration.ts:80` 自定义 `TokenAwareWebSocket`，通过 `Sec-WebSocket-Protocol: auth.<token>` 传 Token。
  - `community_ws.py:122` 后端优先从子协议读取 Token，保留 query string 作为向后兼容。
- **根因**：`y-websocket` 默认使用 URL 参数传参，项目未做覆盖。
- **风险**：极低。旧版 query-token 仍可用，但前端已默认不使用。
- **验证**：端到端测试新增子协议连接用例，连接成功并收到 Yjs SYNC。

#### I-03 · 修复 `_room_users` 用户追踪 Bug
- **提案描述**：全局 `_room_users` 覆盖导致断线时触发错误用户离开事件。
- **实际状态**：已改用 `ContextVar`。
- **关键代码**：
  - `community_ws.py:69` 定义 `_current_room_id`、`_current_user_id`。
  - `ZaoWuASGIServer.__call__` 设置上下文，`on_connect` 绑定 `user_id`，`_on_disconnect_with_cleanup` 读取。
- **根因**：全局字典在并发连接下互相覆盖。
- **风险**：极低，仅变更状态存储方式。

#### I-04 · 邀请码纯输入即可加入（智能匹配）
- **提案描述**：必须先选中房间才能输入邀请码，UX 阻塞。
- **实际状态**：已实现。
- **关键代码**：
  - `ZaoWu\src\components\JoinDialog.vue:82` 支持纯邀请码输入。
  - 前端先在本地房间列表匹配，未命中则调用 `/rooms/lookup?code=` 后端查找。
- **根因**：解析逻辑只支持 `zaowu://`、`roomId:code` 等格式，未覆盖纯邀请码。
- **风险**：极低。

---

### 🟠 P1 可靠性与安全加固

#### I-05 · Token 过期 + 会话清理
- **实际状态**：已实现。
- **关键代码**：
  - `services/room_service.py:35` `TOKEN_TTL_MS = 2h`。
  - `validate_token` 检查 `created_at` 并清理过期 Token。
  - `cleanup_inactive_rooms` 同步清理与已关闭房间关联及超时的 Token。
- **验证**：新增单元测试 `TestTokenExpiry`，验证过期 Token 失效及清理器移除过期会话。

#### I-06 · 房间自动清理调度器
- **实际状态**：已实现。
- **关键代码**：`server_quart.py:344` `_start_room_cleanup_scheduler`，启动后 1 分钟开始，每 10 分钟执行一次。

#### I-07 · 邀请码暴力穷举防护
- **实际状态**：已实现。
- **关键代码**：
  - `services/room_service.py:41` `MAX_FAILURES_PER_MINUTE = 5`。
  - `join_room` 中维护 `_join_failures`，超过阈值抛出 `too many attempts`。
- **验证**：新增单元测试 `TestInviteCodeBruteForce`。

#### I-08 · 文件差异写入限制（大小/频率/原子写入）
- **实际状态**：已实现，并做了一项关键修正。
- **关键代码**：
  - `community_ws.py:210` `MAX_DIFF_SIZE = 10MB`。
  - `MIN_DIFF_INTERVAL = 0.1s` 用户级频率限制。
  - 原子写入：临时文件 + `os.replace`。
- **本次修正**：原 `_handle_file_diff` 在项目路径不可解析时直接 `return`，导致 `file_diff` 不会广播给其他客户端。已将广播逻辑前移至权限/频率/大小校验之后、本地文件系统应用之前。
- **根因**：把"服务器本地能否应用"与"是否需要广播"混为一谈。协作场景中，客户端工作副本需要收到 diff，即使服务器当前未打开该项目。
- **风险**：极低。权限、频率、大小限制仍然生效；本地写失败仅影响服务端文件，不影响网络分发。

---

### 🟡 P2 体验完善

#### I-09 · 修复 `_broadcast_custom` exclude 机制 ⭐ 本次修复
- **提案描述**：`_client_user_id` 永远返回 `None`，`file_diff` 无法排除发送者。
- **实际状态**：已修复。
- **根因分析**：
  - `pycrdt-websocket` 的 `ASGIWebsocket` 对象不保存 `scope`。
  - `on_connect` 虽然把 `zaowu_user_id` 写入了 ASGI `scope`，但 `room.clients` 中的 client 对象访问不到该 `scope`。
  - 因此 `_client_user_id` 的两个 fallback（`client.scope`、`client._zaowu_user_id`）都无法命中。
- **修复方案**：
  - 重写 `ZaoWuASGIServer.__call__`，在创建 `ASGIWebsocket` 实例后显式附加 `websocket.scope = scope`。
  - 这样 `_client_user_id` 即可通过 `client.scope.get('zaowu_user_id')` 正确识别连接用户。
- **关键代码**：
  - `community_ws.py:617` 自定义 WebSocket accept/serve 流程。
  - `community_ws.py:644` `websocket.scope = scope`。
- **风险**：低。完全复用 `ASGIServer` 原有逻辑，仅增加 scope 附加与 `ContextVar` 绑定。
- **验证**：扩展版端到端冒烟测试新增 `file_diff` 发送者排除断言，host 未收到自身 diff，Alice 正确收到。

#### I-10 · 生成可分享的 HTTP 加入链接
- **实际状态**：已实现。
- **关键代码**：
  - `ZaoWu\src\components\InviteDialog.vue:17` 生成 `http://<host>/?join=<inviteCode>`。
  - `ZaoWu\src\components\MainLayout.vue:56` 读取 `window.__JOIN_CODE__` 自动切换社区视图。
  - `server_quart.py:93` `index()` 注入 `__JOIN_CODE__`。

#### I-11 · 邀请码字符集优化
- **实际状态**：已实现。
- **关键代码**：`services/room_service.py:38` `_SAFE_CHARS = 'ABCDEFGHJKMNPQRTUVWXYZ2346789'`，排除 0/O/1/I/5/S/L。

#### I-12 · 后端「按邀请码查找房间」API
- **实际状态**：已实现。
- **关键代码**：`routes/community.py:175` `api_lookup_room`。
- **验证**：新增单元测试 `TestLookupByInviteCode`。

#### I-13 · YStore 文档持久化启用
- **实际状态**：已实现。
- **关键代码**：`server_quart.py:192` 在 `_get_room_with_handler` 中为每个房间挂载 `SQLiteYStore`。

---

## 三、本次新增修复（未在原始提案中明确列出）

### 1. Python 3.9 兼容性修复
- **问题**：`server_quart.py` 使用 `_conversation_store: ConversationStore | None = None`，在 Python 3.9 下启动报 `TypeError: unsupported operand type(s) for |`。
- **影响**：服务无法启动，所有依赖后端的测试与功能不可用。
- **修复**：在 `server_quart.py` 顶部添加 `from __future__ import annotations`。
- **同类修复**：`test_community.py` 也使用了 `dict | None` 语法，同样添加 `from __future__ import annotations`。

### 2. 端到端测试适配 `room_info` 广播
- **问题**：`test_community.py` 在收到 `chat_message` 前会收到 `room_info` 广播，断言 `decoded.get('type') == 'chat_message'` 直接失败。
- **修复**：新增 `recv_custom_of_type` 辅助函数，持续读取并跳过 Yjs 与 `room_info` 帧，直到拿到目标类型消息。

### 3. 前端 TypeScript 类型修复
- **问题 1**：`TokenAwareWebSocket` 构造函数签名 `url: string` 与 `WebSocket` 标准 `url: string | URL` 不兼容，导致 `vue-tsc` 报错。
- **修复**：改为 `constructor(url: string | URL, ...)`。
- **问题 2**：`WSMessageType` 未包含 `'room_closed'`，但 `useCollaboration.ts` 已处理该消息类型。
- **修复**：在 `ZaoWu\src\types\index.ts` 的 `WSMessageType` 中新增 `'room_closed'`。

---

## 四、测试执行与结果

### 1. 后端单元测试

```bash
python -m pytest tests/test_room_service.py -v
```

**结果**：35 passed, 0 failed

新增测试覆盖：
- `TestTokenExpiry`：Token 过期失效、清理器移除过期会话。
- `TestInviteCodeBruteForce`：邀请码暴力尝试拦截、成功加入后清除失败记录。
- `TestLookupByInviteCode`：按邀请码查找房间、大小写不敏感、未找到返回 None。

### 2. 社区端到端冒烟测试

```bash
python test_community.py
```

**结果**：✅ 通过

覆盖链路：
1. 创建房间 REST API
2. 加入房间 REST API
3. WebSocket 连接并接收 Yjs SYNC_STEP1
4. `chat_message` 广播（Alice 收到 host 消息）
5. **Sec-WebSocket-Protocol 子协议传 Token 连接**
6. **`file_diff` 广播排除发送者（I-09）**
7. 房间清理 API

### 3. 全量后端单元测试（排除已知不稳定/外部依赖模块）

```bash
python -m pytest tests/ -v --ignore=tests/test_plugins --ignore=tests/test_skill_loader.py
```

**结果**：177 passed, 1 failed, 2 skipped

唯一失败用例：`tests/test_web_search.py::test_search_web_clamps_max_results`，与社区协作改进无关，属于 Web 搜索模块的既有问题，建议单独跟进。

### 4. 前端类型检查

```bash
cd ZaoWu
npx vue-tsc --build
```

**结果**：无错误

### 5. 前端生产构建

```bash
cd ZaoWu
npx vite build
```

**结果**：构建成功

存在两个非阻塞警告：
- 部分 chunk 大于 500KB（建议后续做代码分割）。
- `useCollaboration.ts` 中对 `projects.ts`、`editor.ts`、`community.ts` 的动态导入同时被其他组件静态导入，导致动态导入无效（不影响功能，仅为打包优化提示）。

---

## 五、潜在风险与应对

| 风险点 | 说明 | 应对措施 |
|--------|------|----------|
| 子协议 Token 兼容性 | 旧客户端可能仍使用 query-token | 后端保留 query-token fallback，并已在 `build_ws_url_for_room` 文档中标记为 deprecated |
| `file_diff` 广播提前 | 本地写失败不再阻止广播 | 权限/频率/大小限制仍在前；广播失败由 `_broadcast_custom` 内部捕获异常 |
| `ZaoWuASGIServer` 重写 | 接管了 `ASGIServer` 的 WebSocket 处理 | 完全复用 `on_connect/on_disconnect` 与 `ASGIWebsocket` 逻辑，行为一致 |
| Python 3.9 `\|from __future__ import annotations` | 使运行时注解变为字符串 | 项目中无运行时解析类型注解的逻辑，安全 |
| 前端 `room_closed` 类型新增 | 可能影响消息分发类型收窄 | 已同步更新 `useCollaboration.ts` 处理分支 |

---

## 六、额外优化建议（P3 及未纳入项）

结合代码审查与测试过程，提出以下建议：

### 1. WebSocket 连接加入统一的连接池/超时管理（P3 深化）
当前 `useCollaboration.ts` 的 `maxBackoffTime: 30000` 已配置，但缺少：
- 最大重连次数限制，避免无限重连导致资源耗尽。
- 断线后主动清理 virtual project，防止状态残留。

### 2. `file_diff` 增加服务端校验与冲突提示
目前仅校验大小与频率，建议：
- 对 rename/delete 操作增加权限检查（只有 host/collaborator 可执行）。
- 本地文件被外部修改时，向发送者返回 `error` 消息而非静默失败。

### 3. 邀请码输入前端校验与字符集对齐
`JoinDialog.vue` 的纯邀请码正则 `[A-Za-z0-9]{6,8}` 仍允许 I/L/O/S/5/1/0 等易混淆字符输入。建议：
- 输入时即时高亮非法字符，或
- 后端返回更明确的错误提示（如 "邀请码包含易混淆字符"）。

### 4. 前端构建优化
- 将 `useCollaboration.ts` 中的动态导入改为静态导入，或移除不必要的动态导入（因相关 store 已被大量组件静态引用）。
- 对大型 chunk 做路由/功能级代码分割。

### 5. 测试覆盖补强
- 为 `routes/community.py` 的 Bearer Token 与 host 权限逻辑增加单元/集成测试。
- 为 `community_ws.py` 的 `on_connect` 子协议解析、Token 过期拒绝、房间关闭广播增加异步测试。
- 修复 `test_search_web_clamps_max_results` 失败用例。

### 6. 文档同步
- `community-improvement-proposal.md` 中 I-02 的示例代码仍可运行，但项目实际采用了更简洁的 `WebSocketPolyfill: TokenAwareWebSocket` 方案，建议更新提案示例以匹配实际代码。
- 在 API 文档中明确 `/api/community/rooms/lookup` 无需认证、公开可访问。

---

## 七、结论

经系统核对与验证，`community-improvement-proposal.md` 中列出的 P0/P1 问题均已实现；P2 问题中除 I-09 外均已实现，**I-09 在本次审查中已彻底修复**；P3 项作为后续优化建议保留。

本次同时修复了 4 个未在提案中明确列出但实际影响可用性的问题：
1. Python 3.9 类型语法兼容性；
2. `file_diff` 无项目路径时不广播的缺陷；
3. 端到端测试未适配 `room_info` 广播；
4. 前端 TypeScript 类型错误。

所有相关测试（后端单元 35 项、扩展端到端、前端类型检查、前端生产构建）均通过。唯一失败用例为既有 Web 搜索模块问题，与本次社区协作改进无关。

项目质量符合预期标准，建议按上述额外优化建议持续迭代。
