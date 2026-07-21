# 社区协作模块审查问题修复结果报告

## 1. 修复概述

针对 `community-improvement-proposal.md` 审查报告中标记为 **🟡 部分修复**、**❌ 未修复** 以及新发现的 **🔴 阻断级** 问题，结合项目实际架构进行系统性修复与验证。本次重点解决以下三项高影响缺陷：

| 编号 | 问题 | 严重程度 | 修复状态 |
|---|---|---|---|
| **P0-2** | **WebSocket Token 加固回归：前端未传 token，所有 WS 连接被拒绝** | **阻断** | **✅ 已修复** |
| P2-2 / I-15 | 服务重启后房间状态恢复不足：无会话持久化、仅靠空闲超时清理 | 高 | ✅ 已修复 |
| P2-3 | `host_id` 冲突：`_host_user_map` 仅存于内存，重启后房主权限判定失效 | 高 | ✅ 已修复 |
| P3-3 / I-17 | 断线重连：`connect:false` 导致自动重连不生效 | 中 | ✅ 已修复（前期已完成） |
| P3-1 / I-16 | 聊天持久化（纯内存广播） | 低 | ❌ 未修复（设计决策） |
| P3-2 / I-14 | LAN 自动发现（仍需手动输 IP） | 低 | ❌ 未修复（设计决策） |
| P3-5 | CORS 精细化（仍允许 localhost 任意端口） | 低 | ❌ 未修复（桌面场景可接受） |

---

## 2. 问题分析与修复方案

### 2.1 P2-3 `host_id` 冲突 —— 持久化房主在房间内的用户 ID

#### 根因分析
- 原实现使用内存字典 `_host_user_map: Dict[str, str]` 记录 `room_id → host_user_id`。
- 该映射由 `routes/community.py` 在创建房间时写入，但 **不持久化**，服务重启后丢失。
- 重启后 `is_host()` 回退到比较 `room.host_id`（机器 UUID）与 `user_id`，导致房主权限判定失效，普通用户可能被误判为房主或房主被剥夺权限。

#### 修复方案
1. 在房间元数据中新增 `host_user_id` 字段，随 `community_rooms.json` 持久化。
2. 房主加入房间后，调用 `set_room_host_user_id(room_id, host_user_id)` 将房内用户 UUID 写回房间元数据。
3. `is_host()`、`leave_room()` 优先使用 `room['host_user_id']`；对旧房间提供 `_migrate_host_user_ids()` 自动回填。
4. 前端类型 `CollaborationRoom` 增加 `hostUserId?: string`。

#### 关键代码
- `services/room_service.py` 第 238–268 行：`_new_room()` 初始化 `host_user_id` 为空字符串。
- `services/room_service.py` 第 326–338 行：`set_room_host_user_id()` 持久化房主用户 ID。
- `services/room_service.py` 第 560–575 行：`is_host()` 优先使用持久化字段。
- `services/room_service.py` 第 178–194 行：`_migrate_host_user_ids()` 为旧房间回填。
- `routes/community.py`：创建房间后调用 `set_room_host_user_id()`。
- `ZaoWu/src/types/index.ts` 第 24 行：`hostUserId?: string`。

---

### 2.2 P2-2 / I-15 重启恢复 —— 用户/会话持久化与启动状态扫描

#### 根因分析
- 用户与会话数据仅存于内存（`_users_by_room`、`_sessions`），服务重启后全部丢失。
- 启动时仅依赖 `cleanup_inactive_rooms()` 的空闲超时清理，没有针对“活跃但无真实连接”的房间进行扫描。
- 结果：重启后房主/成员需重新加入房间，且僵尸活跃房间长期占用资源。

#### 修复方案
1. 新增 `data/collaboration/community_users.json` 与 `community_sessions.json` 持久化文件。
2. 在 `join_room`、`leave_room`、`remove_user`、`validate_token` 过期时自动调用 `_persist_users()` / `_persist_sessions()`。
3. 启动时 `_load_persisted_state()`：
   - 加载用户并统一标记为 `offline`；
   - 丢弃过期会话；
   - 仅保留用户仍然存在的会话；
   - 触发 `_migrate_host_user_ids()` 回填旧房间房主 ID。
4. `server_quart.py` 的 `_recover_room_state()` 在启动时：
   - 先加载持久化状态；
   - 对没有 YStore 文档（从未有过 WS 连接）或超过空闲超时的活跃房间自动关闭。

#### 关键代码
- `services/room_service.py` 第 106–175 行：读写、加载、持久化函数。
- `services/room_service.py` 第 449–452 行：`join_room()` 加入后自动持久化。
- `services/room_service.py` 第 489–502 行：`leave_room()` / `remove_user()` 后自动持久化。
- `server_quart.py` 第 150–206 行：启动恢复逻辑。

---

### 2.3 P3-3 / I-17 断线重连

#### 修复方案
- 前端 `useCollaboration.ts` 中 Yjs provider 初始化后显式调用 `provider.connect()`，确保 `maxBackoffTime` 等重连参数生效，瞬断后可自动恢复。

---

### 2.4 P0-2 WebSocket Token 加固回归 —— 前端必须将 Token 传入 useCollaboration

#### 根因分析
- 后端 `routes/community.py` 在三处返回 `wsUrl` 时均 **不携带 token**（有意避免 token 泄露到日志/历史/Referer）。
- 前端 `stores/community.ts` 将 `token` 与 `wsUrl` 存为独立 ref，但 `CommunityPanel.vue` 调用 `useCollaboration()` 时只传了 `wsUrl`，未传 `token`。
- `UseCollaborationOptions` 接口没有 `token` 字段。
- `useCollaboration.ts` 从 `wsUrl` 的 query string 解析 token，因 URL 无 token 而得到空串，导致 WebSocket 连接不带认证信息。
- 后端 `community_ws.py` 的 `on_connect()` 在无 token 时直接拒绝连接（`if not token: return True`）。
- **结果：编辑、光标、群聊、文件同步在当前版本全部失效。**

#### 子协议方案不可行
初步尝试通过 `Sec-WebSocket-Protocol: auth.${token}` 传递 token，但实测库源码后发现该路径在浏览器端不可行：

- `pycrdt.websocket.ASGIServer.__call__` 在 `on_connect` 通过后发送裸 `websocket.accept`，**不回显** `Sec-WebSocket-Protocol`。
- 浏览器遵循 RFC 6455 §4.1：客户端握手带了子协议而 101 响应未回显时，会主动拒绝握手。
- 因此子协议方案只是把“后端拒绝”换成了“浏览器拒绝”，问题未解决。

#### 修复方案（采用方案 A：query string）
1. 在 `UseCollaborationOptions` 接口中增加 `token: string` 字段。
2. 修改 `useCollaboration.ts`：
   - 使用 `options.token` 作为认证 token；
   - 通过 y-websocket 的 `params` 选项将 token 追加为 URL query string（`?token=...`）；
   - **移除 `TokenAwareWebSocket` 子协议注入逻辑**，避免触发浏览器子协议回显校验失败。
3. 修改 `CommunityPanel.vue`，调用 `useCollaboration()` 时传入 `store.token`。
4. 后端 `community_ws.py` 保持现有 query-string token 读取逻辑不变。
5. 更新 `test_community.py`：主连接改用 URL query-string 传 token，匹配生产前端行为。

> 方案 B（继承 ASGIServer 覆写 `__call__` 回显子协议）安全合规但改动大、有库升级兼容风险，本次未采用；如后续有强合规需求可再评估。

#### 关键代码
- `ZaoWu/src/composables/useCollaboration.ts` 第 12–19 行：`UseCollaborationOptions` 增加 `token`。
- `ZaoWu/src/composables/useCollaboration.ts` 第 81–96 行：通过 `params: token ? { token } : {}` 将 token 追加到 WebSocket URL。
- `ZaoWu/src/components/CommunityPanel.vue` 第 31–38 行：传入 `token: store.token`。
- `community_ws.py` 第 135–143 行：从 query string 读取 token 的兜底逻辑。

#### 后续清理
- 修正了三处仍在推荐 `Sec-WebSocket-Protocol` 的误导性注释：
  - `community_ws.py` 中 `build_ws_url` 与 `build_ws_url_for_room` 的 docstring
  - `routes/community.py` 中返回 `wsUrl` 处的行内注释
- 移除了死代码：
  - 前端 `ZaoWu/src/services/community.ts` 中的 `getWsUrl()`
  - 后端 `routes/community.py` 中的 `/rooms/<room_id>/ws-url` 端点 `api_get_ws_url()`

---

## 3. 测试补充

针对上述两项核心修复，在 `tests/test_room_service.py` 新增两个测试类：

### 3.1 `TestHostUserIdPersistence`

| 用例 | 覆盖点 |
|---|---|
| `test_host_user_id_persisted_on_room` | 设置房主 ID 后写入 `community_rooms.json` |
| `test_is_host_uses_persisted_host_user_id` | `is_host()` 正确判定房主身份 |
| `test_host_leaving_closes_room_and_removes_sessions` | 房主离开后关闭房间、清除所有用户与会话 |
| `test_migrate_host_user_ids_backfills_legacy_room` | 旧房间无 `host_user_id` 时自动回填 |

### 3.2 `TestSessionPersistence`

| 用例 | 覆盖点 |
|---|---|
| `test_sessions_persisted_to_disk` | 加入房间后 `community_sessions.json` 存在且内容正确 |
| `test_load_persisted_state_restores_sessions` | 模拟重启后恢复会话，`validate_token()` 有效 |
| `test_load_persisted_state_drops_expired_sessions` | 过期会话在加载时被丢弃 |
| `test_load_persisted_state_marks_users_offline` | 加载后的用户状态为 `offline` |

---

## 4. 测试结果

### 4.1 后端单元测试

```text
tests/test_room_service.py: 43 passed
```

全量后端测试：

```text
198 passed, 2 skipped, 1 failed
```

- 唯一失败：`tests/test_web_search.py::test_search_web_clamps_max_results`，与社区模块无关，属既有问题。
- 新增 8 个测试用例全部通过。

### 4.2 端到端冒烟测试

运行 `test_community.py`，覆盖：

1. 创建房间（响应中已包含 `hostUserId`）。
2. 邀请码加入。
3. WebSocket 连接（**主路径：通过 URL query string `?token=<token>` 传 Token**）并接收 Yjs SYNC_STEP1。
4. 自定义 `chat_message` 广播。
5. `file_diff` 广播排除发送者。
6. 房间清理。

结果：✅ 全部断言通过。

### 4.3 前端验证

- `npm run type-check`：无 TypeScript 错误。
- `npm run build-only`：生产构建成功（仅有既有 chunk 大小警告，非错误）。

---

## 5. 未修复项说明

| 编号 | 问题 | 未修复原因 |
|---|---|---|
| P3-1 / I-16 | 聊天持久化 | 当前社区协作定位为实时协作，聊天采用内存广播符合设计；持久化将引入存储策略、隐私与合规复杂度，需单独产品决策。 |
| P3-2 / I-14 | LAN 自动发现 | 自动发现依赖 mDNS/SSDP 等网络协议，跨平台实现复杂且在企业网络中常受限；当前邀请码 + 标准 HTTP URL 已满足主要场景。 |
| P3-5 | CORS 精细化 | 桌面应用绑定本地服务，允许 `localhost/127.0.0.1` 任意端口是预期行为；已添加 Origin 白名单中间件拒绝非本地写操作，风险可控。 |

---

## 6. 优化建议

1. **持久化文件备份**：`community_users.json` / `community_sessions.json` 可考虑写时备份（如 `.bak`），避免异常崩溃导致空文件。
2. **房主迁移**：当前房主离开即关闭房间。后续可考虑“转让房主”功能，提升房间生命周期灵活性。
3. **会话续期**：当前 Token 固定 2 小时 TTL。在线用户可通过 WebSocket 心跳自动续期，减少重登频率。
4. **监控指标**：在 `_recover_room_state()` 中已记录关闭原因计数，可进一步暴露到 `/api/health` 或日志聚合。
5. **邀请码易混淆字符**：已排除 `0/O/1/I/5/S/L`，建议后续根据用户反馈继续收紧字符集。

---

## 7. 风险与回滚

| 风险 | 缓解措施 |
|---|---|
| 旧房间无 `host_user_id` | `_migrate_host_user_ids()` 启动时自动回填 |
| 持久化文件损坏 | `_read_json_file()` 捕获异常后返回空字典，服务可继续运行 |
| 启动恢复失败阻塞服务 | `_recover_room_state()` 捕获全部异常并记录日志后继续 |
| 并发写入状态文件 | 使用 `_room_lock`（threading.RLock）保护 |

如需回滚，可恢复以下文件至修复前版本：

- `services/room_service.py`
- `server_quart.py`
- `routes/community.py`
- `community_ws.py`
- `ZaoWu/src/types/index.ts`
- `ZaoWu/src/composables/useCollaboration.ts`
- `ZaoWu/src/components/CommunityPanel.vue`
- `ZaoWu/src/services/community.ts`
- `tests/test_room_service.py`
- `test_community.py`

---

## 8. 结论

本次修复彻底解决了社区模块中的 **阻断级 WebSocket Token 传递回归**、**房主权限重启丢失** 与 **服务重启状态恢复不足** 问题，补充了针对性单元测试并更新了端到端冒烟测试，通过后端全量测试、端到端冒烟测试、前端类型检查及生产构建验证，确认未引入回归。未修复项均为设计决策或低优先级增强，不影响当前核心功能稳定性。
