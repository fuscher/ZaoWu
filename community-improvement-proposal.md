# ZaoWu 社区协作 — 改进建议报告

> **编制日期**：2026-07-21  
> **基于**：架构代码审查 + LAN 场景可用性分析  
> **原则**：只提改进建议，不重复问题描述；按优先级排列，附带实现思路和预估工作量

---

## 改进清单总览

| 编号 | 改进项 | 类型 | 优先级 | 工作量 |
|------|--------|------|--------|--------|
| I-01 | REST API 增加 Bearer Token 认证 | 🔒 安全 | 🔴 P0 | 1天 |
| I-02 | WebSocket Token 加固（子协议传递） | 🔒 安全 | 🔴 P0 | 半天 |
| I-03 | 修复 `_room_users` 用户追踪 Bug | 🐛 缺陷 | 🔴 P0 | 1小时 |
| I-04 | 邀请码纯输入即可加入（智能匹配） | ✨ 体验 | 🔴 P0 | 半天 |
| I-05 | Token 过期 + 会话清理机制 | 🔒 安全 | 🟠 P1 | 2小时 |
| I-06 | 房间自动清理调度器 | 🏗 可靠性 | 🟠 P1 | 1小时 |
| I-07 | 邀请码暴力穷举防护 | 🔒 安全 | 🟠 P1 | 1小时 |
| I-08 | 文件差异写入限制（大小/频率） | 🏗 可靠性 | 🟠 P1 | 1小时 |
| I-09 | 修复 `_broadcast_custom` exclude 机制 | 🐛 缺陷 | 🟡 P2 | 1小时 |
| I-10 | 生成可分享的 HTTP 加入链接 | ✨ 体验 | 🟡 P2 | 1小时 |
| I-11 | 邀请码字符集优化（排除易混淆字符） | ✨ 体验 | 🟡 P2 | 半小时 |
| I-12 | 后端「按邀请码查找房间」API | 🏗 架构 | 🟡 P2 | 1小时 |
| I-13 | YStore 文档持久化启用 | 🏗 可靠性 | 🟡 P2 | 1小时 |
| I-14 | LAN 房间自动发现（UDP 广播） | ✨ 体验 | 🔵 P3 | 1天 |
| I-15 | 服务重启状态恢复 | 🏗 可靠性 | 🔵 P3 | 半天 |
| I-16 | 聊天消息持久化 | ✨ 体验 | 🔵 P3 | 半天 |
| I-17 | WebSocket 断线重连参数配置 | 🏗 可靠性 | 🔵 P3 | 半小时 |
| I-18 | `zaowu://` 协议 → HTTP 链接改造 | ✨ 体验 | 🔵 P3 | 1小时 |
| I-19 | 房间关闭时广播通知在线客户端 | ✨ 体验 | 🔵 P3 | 半小时 |

---

## 🔴 P0 — 安全与体验阻塞项（必须立即修复）

### I-01 · REST API 增加 Bearer Token 认证

**当前状态**：所有 `/api/community/rooms/*` 端点零鉴权，局域网任意设备可操作。

**改进方案**：利用现有 WebSocket Token 机制为 REST 端点增设认证。

**后端改动**（`routes/community.py`）：

```python
# 新增装饰器：要求 Bearer Token
from functools import wraps
from services.room_service import validate_token

def require_token(f):
    @wraps(f)
    async def wrapper(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'ok': False, 'error': 'unauthorized'}), 401
        session = validate_token(auth[7:].strip())
        if not session:
            return jsonify({'ok': False, 'error': 'invalid or expired token'}), 401
        request.zaowu_session = session
        return await f(*args, **kwargs)
    return wrapper

# 需要鉴权的端点加上装饰器
@community_bp.route('/rooms/<room_id>', methods=['DELETE'])
@require_token
async def api_close_room(room_id): ...

@community_bp.route('/rooms/<room_id>/users/<user_id>', methods=['DELETE'])
@require_token
async def api_remove_user(room_id, user_id): ...

# 公开端点保持无需认证
@community_bp.route('/rooms', methods=['GET'])
async def api_list_rooms(): ...  # 房间列表公开（LAN 发现需要）

@community_bp.route('/rooms/<room_id>/join', methods=['POST'])
async def api_join_room(room_id): ...  # 加入仅靠邀请码控制
```

**涉及文件**：`routes/community.py`

**额外收益**：为后续 API 端点细化权限（如只有 host 能关房间、踢人）铺路。

---

### I-02 · WebSocket Token 加固 — 优先使用子协议传递

**当前状态**：Token 通过 URL 查询参数 `?token=xxx` 传递，暴露在浏览器历史、日志、Referer 中。

**改进方案**：后端已支持 `Sec-WebSocket-Protocol` 子协议认证（`community_ws.py:116-127`），前端改为使用子协议即可。

**前端改动**（`useCollaboration.ts`）：

```typescript
// ❌ 当前：token 走 URL 查询参数
const provider = new WebsocketProvider(serverUrl, options.roomId, doc, {
  awareness,
  params: token ? { token } : {},  // 废弃
})

// ✅ 改为：token 走 Sec-WebSocket-Protocol 子协议
// 注意：y-websocket 的 WebsocketProvider 构造函数不支持直接设置子协议，
// 需要通过自定义 WebSocket 工厂实现
class TokenAwareWebSocket extends WebSocket {
  constructor(url: string, protocols?: string | string[]) {
    super(url, protocols)
  }
}

const wsUrl = `ws://${parser.host}${basePath}/${options.roomId}`
const ws = new TokenAwareWebSocket(wsUrl, ['auth.' + token])
```

或者更简单地，利用 `y-websocket` 已有的 `WebSocketPolyfill` 选项：

```typescript
const provider = new WebsocketProvider(serverUrl, options.roomId, doc, {
  awareness,
  WebSocketPolyfill: (url: string, protocols?: string[]) => {
    const finalProtocols = token ? [...(protocols || []), `auth.${token}`] : protocols
    return new WebSocket(url, finalProtocols)
  },
  // 同时移除 URL 中的 token 参数
  params: {},
})
```

**后端**（已就绪，无需改动）：`community_ws.py:116-127` 已实现子协议优先读取逻辑。

---

### I-03 · 修复 `_room_users` 用户追踪 Bug

**当前状态**：每次新 WebSocket 连接覆盖前一个用户的 ID，导致断线时触发错误的用户离开事件。

**改进方案**：改用 scope-level 存储（利用已有的 ContextVar 机制）。

**后端改动**（`community_ws.py`）：

```python
# ❌ 当前：全局 dict，每个房间一个 key
_room_users: dict[str, str] = {}

# ✅ 改为：利用 scope 传递 user_id，在 disconnect 时从 ContextVar 读取
# 新增 ContextVar 存储当前连接的用户 ID
_current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar('_current_user_id', default='')

# on_connect 中不再写全局 dict，改为设 ContextVar
def set_current_user_context(room_id: str, user_id: str) -> None:
    """在 ZaoWuASGIServer.__call__ 中，scope 处理完毕后设置当前用户上下文。"""
    _current_room_id.set(room_id)
    _current_user_id.set(user_id)

# _on_disconnect_with_cleanup 改为从 ContextVar 读取
def _on_disconnect_with_cleanup(message: dict[str, Any]) -> None:
    room_id = _current_room_id.get('')
    user_id = _current_user_id.get('')
    if room_id and user_id:
        _room_project_paths.pop(room_id, None)
        _room_close_callbacks.pop(room_id, None)
        _fire_user_hook('zaowu_on_user_left', room_id, user_id)
```

**涉及文件**：`community_ws.py`（删除 `_room_users` dict，新增一个 ContextVar）

**风险**：极低，改动仅涉及变量类型变更。

---

### I-04 · 邀请码纯输入即可加入（智能匹配）

**当前状态**：纯输入邀请码（如 `D9YEUS`）必须搭配"先从房间列表选中房间"才能点击加入按钮，这是一个严重的 UX 阻塞点。

**改进方案**：前端在解析时自动遍历现有房间列表匹配邀请码。

**前端改动**（`JoinDialog.vue`）：

```typescript
const parsed = computed(() => {
  const link = inviteLink.value.trim()
  if (!link) {
    if (selectedRoom.value?.inviteCode) {
      return { roomId: selectedRoom.value.id, inviteCode: selectedRoom.value.inviteCode }
    }
    return null
  }

  // ... 现有 zaowu:// / UUID:code / 空格分隔 解析逻辑保持不变 ...

  // ★ 纯邀请码（6-8 位字母数字）— 遍历活跃房间列表自动匹配
  const plainCodeMatch = link.match(/^[A-Za-z0-9]{6,8}$/)
  if (plainCodeMatch) {
    const code = link.toUpperCase()
    // 1. 如果已预选了房间且邀请码匹配
    if (selectedRoom.value?.inviteCode === code) {
      return { roomId: selectedRoom.value.id, inviteCode: code }
    }
    // 2. 遍历活跃房间列表，找到邀请码匹配的房间
    const matched = store.rooms.find(r => r.inviteCode === code)
    if (matched) {
      return { roomId: matched.id, inviteCode: code }
    }
    // 3. 都没匹配 — 返回 null（按钮禁用 + 错误提示）
    error.value = t('community.inviteCodeNotFound')  // "未找到匹配的房间，请确认邀请码"
    return null
  }

  return null
})
```

同时将 `error` 改为 computed 在解析失败时自动显示提示，而非仅在 submit 时才报错。

**涉及文件**：`JoinDialog.vue`

---

## 🟠 P1 — 可靠性与安全加固

### I-05 · Token 过期 + 会话清理

**改进方案**：在 `validate_token` 中增加超时检查，在 `cleanup_inactive_rooms` 中同步清理过期 session。

**后端改动**（`services/room_service.py`）：

```python
TOKEN_TTL_MS = 2 * 60 * 60 * 1000  # 2 小时

def validate_token(token: str) -> Optional[Dict[str, Any]]:
    session = _sessions.get(token)
    if not session:
        return None
    # Token 过期检查
    if _now_ms() - session['created_at'] > TOKEN_TTL_MS:
        _sessions.pop(token, None)
        return None
    return session

def cleanup_inactive_rooms() -> int:
    """关闭不活跃房间 + 清理过期 token"""
    data = _read_rooms()
    now = _now_ms()
    timeout_ms = _room_inactive_timeout_minutes() * 60 * 1000
    closed = 0
    for room in data.get('rooms', []):
        if room['status'] == 'active' and now - room.get('updated_at', 0) > timeout_ms:
            room['status'] = 'closed'
            room['updated_at'] = now
            # 清理该房间的所有 token
            expired = [t for t, s in _sessions.items() if s['room_id'] == room['id']]
            for t in expired:
                _sessions.pop(t, None)
            closed += 1
    if closed:
        _write_rooms(data)
    return closed
```

---

### I-06 · 房间自动清理调度器

**改进方案**：在 `server_quart.py` 的 `before_serving` 中启动后台异步任务。

```python
@app.before_serving
async def _start_room_cleanup():
    async def _loop():
        await asyncio.sleep(60)  # 启动后等 1 分钟再开始
        while True:
            await asyncio.sleep(600)  # 每 10 分钟
            try:
                closed = cleanup_inactive_rooms()
                if closed:
                    _logger.info('auto-cleanup: closed %d rooms', closed)
            except Exception:
                _logger.exception('cleanup failed')
    asyncio.ensure_future(_loop())
```

---

### I-07 · 邀请码暴力穷举防护

**改进方案**：加入失败计数器 + 指数退避。

```python
_join_failures: Dict[str, list] = {}  # room_id → [timestamps]
MAX_FAILURES_PER_MINUTE = 5

def join_room(room_id, invite_code, user_name):
    # 检查失败频率
    now = _now_ms()
    failures = [t for t in _join_failures.get(room_id, []) if now - t < 60_000]
    if len(failures) >= MAX_FAILURES_PER_MINUTE:
        raise RoomServiceError('too many attempts, please wait')

    room = get_room(room_id)
    # ... 现有校验 ...

    if room['invite_code'] != invite_code.upper():
        _join_failures.setdefault(room_id, []).append(now)
        raise RoomServiceError('invalid invite code')

    # 成功 → 清除失败记录
    _join_failures.pop(room_id, None)
    # ... 继续加入逻辑 ...
```

---

### I-08 · 文件差异写入限制

**改进方案**：增加大小上限 + 频率限制 + 原子写入。

```python
# community_ws.py 新增常量
MAX_DIFF_SIZE = 10 * 1024 * 1024   # 单次写入最大 10MB
_user_diff_timestamps: dict[str, float] = {}  # user_id → last diff time
MIN_DIFF_INTERVAL = 0.1  # 同一用户两次写入间隔至少 100ms

async def _handle_file_diff(room: YRoom, payload: dict[str, Any]) -> None:
    # ... 现有权限校验 ...

    # 频率限制
    if user_id:
        last = _user_diff_timestamps.get(user_id, 0)
        import time
        if time.time() - last < MIN_DIFF_INTERVAL:
            return
        _user_diff_timestamps[user_id] = time.time()

    # 大小限制
    if content is not None and len(str(content).encode('utf-8')) > MAX_DIFF_SIZE:
        logger.warning('file_diff rejected: exceeds %d bytes', MAX_DIFF_SIZE)
        return

    # 原子写入（写临时文件 → rename，防止写入中断导致文件损坏）
    target = _safe_path(project_path, path)
    tmp = target + '.tmp.' + str(uuid.uuid4())[:8]
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(str(content))
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
```

---

## 🟡 P2 — 体验完善

### I-09 · 修复 `_broadcast_custom` exclude 机制

`_client_user_id` 永远返回 `None`，导致文件差异广播时无法排除发送者。虽由前端兜底去重，但应修复后端以保证数据一致性。

**改进方案**：利用 `scope` 上的 `zaowu_user_id`，在客户端加入房间时将 user_id 绑定到 YRoom client 元数据。

```python
# community_ws.py 修改 _client_user_id
def _client_user_id(client: Any) -> str | None:
    return getattr(client, '_zaowu_user_id', None)

# 在 on_connect 中将 user_id 绑定到 client（通过 scope 传递）
# 或在 set_custom_message_handler 时从 scope 提取并存储
```

---

### I-10 · 生成可分享的 HTTP 加入链接

**改进方案**：在邀请弹窗中生成标准 HTTP URL，而非 `zaowu://` 自定义协议。

```typescript
// InviteDialog.vue
function getJoinUrl(): string {
  const host = store.currentRoom?.hostAddress || window.location.host
  const code = store.currentRoom?.inviteCode || ''
  return `http://${host}/?join=${code}`
}
```

后端在 `index()` 路由中解析 `?join=` 参数，注入到前端全局设置中，由前端自动弹出加入对话框。

---

### I-11 · 邀请码字符集优化

排除易混淆字符：`0` `O` `1` `I` `L` `5` `S` → 从 36 字符集缩减为 29 字符集（或使用明确区分的大小写方案）。

```python
# services/room_service.py
_SAFE_CHARS = 'ABCDEFGHJKMNPQRTUVWXYZ2346789'  # 去除了 0/O/1/I/5/S/L
_INVITE_CODE_LENGTH = 6  # 29^6 ≈ 5.9 亿，仍足够安全
```

---

### I-12 · 后端「按邀请码查找房间」API

配合 I-04 的前端自动匹配，增加一个后端 API 作为可靠后备。

```python
@community_bp.route('/rooms/lookup', methods=['GET'])
async def api_lookup_room():
    code = request.args.get('code', '').strip().upper()
    if not code or len(code) < 6:
        return jsonify({'ok': False, 'error': 'invalid code'}), 400
    rooms = list_rooms()
    matched = next((r for r in rooms if r['invite_code'] == code), None)
    if not matched:
        return jsonify({'ok': False, 'error': 'room not found'}), 404
    return jsonify({
        'ok': True,
        'room': _to_camel({
            'id': matched['id'],
            'name': matched['name'],
            'hostAddress': matched['host_address'],
        }),
    })
```

---

### I-13 · YStore 文档持久化启用

`make_ystore()` 已定义但从未调用，Yjs 文档内容在服务重启后可能丢失。

**改进方案**：在 `_get_room_with_handler` 中挂载 ystore。

```python
# server_quart.py _startup_ws_server 中
async def _get_room_with_handler(name: str):
    room = await _original_get_room(name)
    if not room.on_message:
        community_ws.set_custom_message_handler(room)
    # 启用 ystore
    if not hasattr(room, '_ystore_set'):
        import re
        match = re.match(r'^/api(?:/v\d+)?/community/ws/(.+)$', name)
        if match:
            ystore = community_ws.make_ystore(match.group(1))
            if ystore:
                room.ystore = ystore
        room._ystore_set = True
    return room
```

---

## 🔵 P3 — 长期优化

### I-14 · LAN 房间自动发现（UDP 广播）

**后端**：每 30 秒发送 UDP 广播包 `{"type":"zaowu_announce","host":"192.168.0.112:5000","rooms":3}`  
**前端**：无法直接监听 UDP，需后端提供 `GET /api/community/discover`（扫描已知 IP 段）或 WebSocket 接收广播事件。

由于浏览器沙箱限制，实际推荐方案是**后端 UDP 监听 + REST API 暴露**：

```python
# 新增 services/lan_discovery.py
import socket, json, threading, time

class LANDiscovery:
    BROADCAST_PORT = 5001
    
    def __init__(self):
        self._peers: dict[str, float] = {}  # host → last_seen
        self._running = False

    def start(self):
        self._running = True
        self._listener = threading.Thread(target=self._listen, daemon=True)
        self._broadcaster = threading.Thread(target=self._broadcast, daemon=True)
        self._listener.start()
        self._broadcaster.start()

    def _listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', self.BROADCAST_PORT))
        while self._running:
            data, addr = sock.recvfrom(1024)
            try:
                msg = json.loads(data)
                if msg.get('type') == 'zaowu_announce':
                    self._peers[msg['host']] = time.time()
            except: pass

    def _broadcast(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self._running:
            host = _get_local_ip()
            rooms = len(list_rooms())
            msg = json.dumps({'type':'zaowu_announce','host':f'{host}:5000','rooms':rooms})
            sock.sendto(msg.encode(), ('255.255.255.255', self.BROADCAST_PORT))
            time.sleep(30)
```

---

### I-15 · 服务重启状态恢复

启动时扫描标记为 `active` 的房间，检查是否还有活跃的 `.ydoc` 文件，无则标记为 `closed`，并在前端重连时给出友好提示。

---

### I-16 · 聊天消息持久化

利用现有 `services/conversation_store.py` 的 SQLite 基础设施，新增 `collab_messages` 表，消息落地存储。

---

### I-17 · WebSocket 断线重连参数

```typescript
const provider = new WebsocketProvider(serverUrl, roomId, doc, {
  awareness,
  maxBackoffTime: 30000,  // 最大退避 30 秒
  connect: true,
})
```

---

### I-18 · `zaowu://` 协议 → HTTP 链接

`CommunityPanel.vue:150` 的 `copyInviteLink()` 和 `JoinDialog.vue:44` 的解析逻辑统一改为标准 HTTP URL 方案，与 I-10 协调。

---

### I-19 · 房间关闭时广播通知

`close_room()` 中向房间所有 WebSocket 客户端广播 `room_closed` 消息，前端收到后自动清理状态并回到首页。

---

## 执行路线建议

```
第一轮（紧急，预计 2 天）
├─ I-03  修复 _room_users Bug              [1h]  代码安全
├─ I-01  REST API Bearer Token 认证        [1d]  安全防线
├─ I-04  邀请码智能匹配                     [0.5d] 体验阻塞
├─ I-05  Token 过期机制                    [2h]  安全防线
├─ I-06  自动清理调度器                     [1h]  可靠性
├─ I-07  邀请码暴力防护                     [1h]  安全防线
└─ I-08  文件差异写入限制                   [1h]  可靠性

第二轮（重要，预计 1.5 天）
├─ I-02  WS Token 子协议传递               [0.5d] 安全加固
├─ I-09  修复 broadcast exclude 机制        [1h]  缺陷修复
├─ I-10  生成 HTTP 加入链接                 [1h]  体验改善
├─ I-11  邀请码字符集优化                    [0.5h] 体验改善
├─ I-12  按邀请码查找房间 API               [1h]  架构补全
└─ I-13  YStore 文档持久化                  [1h]  可靠性

第三轮（锦上添花，预计 2-3 天）
├─ I-14  LAN 房间自动发现                   [1d]  体验亮点
├─ I-15  服务重启状态恢复                    [0.5d] 容灾
├─ I-16  聊天持久化                          [0.5d] 体验
├─ I-17  断线重连配置                        [0.5h] 可靠性
├─ I-18  zaowu:// 协议 → HTTP               [1h]  体验
└─ I-19  房间关闭广播                        [0.5h] 体验
```

---

## 未纳入本次的建议（需更多讨论）

| 建议 | 原因 |
|------|------|
| 全链路 TLS 加密 (`wss://`) | 桌面应用技术可行但需自签名证书管理方案，建议单独评估 |
| 多 IDE 协作支持 | 需要标准化 WebSocket 端点 + IDE 插件，非短期可落地 |
| 离线编辑冲突合并 | 需要 OT/CRDT 持久化层改造，当前需求不明确 |
| 二维码分享 | 依赖 I-10 完成后才有稳定的 URL 可编码，P3 补充项目 |
