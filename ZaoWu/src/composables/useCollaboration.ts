import { ref, computed, onUnmounted } from 'vue'
import * as Y from 'yjs'
import { WebsocketProvider } from 'y-websocket'
import { Awareness } from 'y-protocols/awareness'
import type {
  CollaborationUser,
  CollaborationCursor,
  WSMessage,
  PermissionMatrix,
} from '@/types'

export interface UseCollaborationOptions {
  roomId: string
  userId: string
  wsUrl: string
  token: string
  userName: string
  userColor: string
}

/** Magic prefix byte that marks ZaoWu custom JSON messages. */
const ZAOWU_PREFIX = 0xf0

/** Encode a WSMessage-like payload as a 0xF0-prefixed binary frame. */
function encodeCustomMessage(payload: Record<string, unknown>): Uint8Array<ArrayBuffer> {
  const json = JSON.stringify(payload)
  const encoder = new TextEncoder()
  const data = encoder.encode(json)
  const msg = new Uint8Array(1 + data.length)
  msg[0] = ZAOWU_PREFIX
  msg.set(data, 1)
  return msg as Uint8Array<ArrayBuffer>
}

function decodeCustomMessage(data: Uint8Array | ArrayBuffer): WSMessage | null {
  const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : data
  if (bytes.length < 2 || bytes[0] !== ZAOWU_PREFIX) return null
  try {
    const decoder = new TextDecoder()
    const json = decoder.decode(bytes.slice(1))
    return JSON.parse(json) as WSMessage
  } catch {
    return null
  }
}

export function useCollaboration(options: UseCollaborationOptions) {
  const status = ref<'connecting' | 'connected' | 'disconnected' | 'reconnecting' | 'error'>('disconnected')
  const _synced = ref(false)  // y-websocket sync marker (internal, not consumed by UI yet)
  const users = ref<CollaborationUser[]>([])
  const chatMessages = ref<{ userId: string; content: string; timestamp: number }[]>([])
  const fileDiffs = ref<{ userId: string; operation: string; path: string; timestamp: number }[]>([])
  const permissions = ref<PermissionMatrix | null>(null)
  const error = ref('')
  let _initialSyncSent = false

  const doc = new Y.Doc()
  const awareness = new Awareness(doc)

  // y-websocket constructs the WebSocket URL as:
  //   serverUrl + '/' + roomname + '?' + urlParams
  // Our wsUrl from the REST API has the form:
  //   ws://host:port/api/v1/community/ws/<roomId>
  //
  // We need to split this into:
  //   serverUrl = ws://host:port/api/v1/community/ws    (path without roomId)
  //   roomname  = <roomId>                            (will be appended by y-websocket)
  const parser = new URL(options.wsUrl)
  const wsPath = parser.pathname
  // The path is /api/v1/community/ws/<roomId> — split off the roomId
  const lastSlash = wsPath.lastIndexOf('/')
  const basePath = wsPath.slice(0, lastSlash)           // /api/v1/community/ws

  // Build the clean server base URL: ws://host:port/api/v1/community/ws
  const serverUrl = `ws://${parser.host}${basePath}`

  // Use the token passed by the caller. Fallback to URL query string only for
  // backwards compatibility with old server responses.
  const token = options.token || parser.searchParams.get('token') || ''

  // Pass the token as a URL query parameter.
  // Note: We previously used Sec-WebSocket-Protocol, but pycrdt-websocket's
  // ASGIServer does not echo the selected subprotocol in websocket.accept, so
  // browsers reject the handshake per RFC 6455 §4.1. Query string is acceptable
  // for the LAN desktop use case and is already supported by on_connect.
  const provider = new WebsocketProvider(
    serverUrl,
    options.roomId,
    doc,
    {
      awareness,
      params: token ? { token } : {},
      maxBackoffTime: 30000,
      // Let y-websocket manage connection lifecycle (initial connect + reconnect).
      // connect: false would require manual provider.connect() and can prevent
      // transient-disconnection auto-recovery in some y-websocket versions.
      connect: true,
    },
  )

  // ── y-websocket status mapping ──────────────────────────────

  function mapProviderStatus(s: string): typeof status.value {
    switch (s) {
      case 'connected':
        return 'connected'
      case 'connecting':
        return 'connecting'
      case 'disconnected':
        return 'disconnected'
      default:
        return 'error'
    }
  }

  provider.on('status', (event: { status: string }) => {
    status.value = mapProviderStatus(event.status)
    if (event.status === 'connected') {
      error.value = ''
    }
  })

  provider.on('sync', (isSynced: boolean) => {
    _synced.value = isSynced
    if (isSynced && !_initialSyncSent) {
      _initialSyncSent = true
      sendCustomMessage({
        type: 'awareness_update',
        roomId: options.roomId,
        userId: options.userId,
        payload: {
          id: options.userId,
          name: options.userName,
          color: options.userColor,
          status: 'online',
        },
        timestamp: Date.now(),
      })
    }
  })

  provider.on('connection-close', (event: CloseEvent | null, _provider: WebsocketProvider) => {
    error.value = 'connection closed'
    status.value = 'disconnected'
  })

  provider.on('connection-error', (event: Event, _provider: WebsocketProvider) => {
    error.value = 'connection error'
    status.value = 'error'
  })

  // ── Custom message listener on the raw WebSocket ────────────
  // y-websocket handles Yjs binary messages (0x00/0x01) automatically.
  // We intercept 0xF0 messages from the same WebSocket for chat, file diff, etc.

  function attachCustomListener() {
    const ws = provider.ws
    if (!ws) return
    const rawOnMessage = ws.onmessage

    ws.onmessage = (event: MessageEvent) => {
      const raw = event.data

      // Try to decode as ZaoWu custom message first
      if (raw instanceof ArrayBuffer || raw instanceof Uint8Array) {
        const custom = decodeCustomMessage(raw)
        if (custom) {
          handleMessage(custom)
          return
        }
      }

      // Fall through to y-websocket's handler for Yjs binary messages
      if (typeof rawOnMessage === 'function') {
        rawOnMessage.call(ws, event)
      }
    }
  }

  // Attach once the provider opens the WebSocket
  provider.on('status', (event: { status: string }) => {
    if (event.status === 'connected') {
      attachCustomListener()
    }
  })

  // ── Computed user state ─────────────────────────────────────

  const currentUser = computed<CollaborationUser>(() => ({
    id: options.userId,
    name: options.userName,
    color: options.userColor,
    role: permissions.value
      ? permissions.value.kick
        ? 'host'
        : permissions.value.edit
          ? 'collaborator'
          : 'observer'
      : 'collaborator',
    status: status.value === 'connected' ? 'online' : 'offline',
    permissions: permissions.value || undefined,
  }))

  const onlineUsers = computed(() =>
    [currentUser.value, ...users.value].filter((u) => u.status === 'online'),
  )

  // ── Incoming message router ─────────────────────────────────

  function handleMessage(message: WSMessage) {
    switch (message.type) {
      case 'room_state': {
        const payload = message.payload as {
          users?: CollaborationUser[]
          permissions?: PermissionMatrix
        }
        if (payload.users) {
          users.value = payload.users.filter((u) => u.id !== options.userId)
        }
        if (payload.permissions) {
          permissions.value = payload.permissions
        }
        break
      }
      case 'user_joined': {
        const payload = message.payload as { user?: CollaborationUser }
        const user = payload.user
        if (user && user.id !== options.userId) {
          const idx = users.value.findIndex((u) => u.id === user.id)
          if (idx >= 0) {
            users.value[idx] = { ...users.value[idx], ...user, status: 'online' }
          } else {
            users.value.push({ ...user, status: 'online' })
          }
        }
        break
      }
      case 'user_left': {
        const payload = message.payload as { userId?: string }
        const leftUserId = payload.userId
        if (leftUserId) {
          const idx = users.value.findIndex((u) => u.id === leftUserId)
          if (idx >= 0) {
            const existing = users.value[idx]
            if (existing) {
              users.value[idx] = { ...existing, status: 'offline' }
            }
          }
        }
        break
      }
      case 'awareness_update': {
        const payload = message.payload as Partial<CollaborationUser>
        const awarenessId = payload.id
        if (!awarenessId || awarenessId === options.userId) break
        const idx = users.value.findIndex((u) => u.id === awarenessId)
        if (idx >= 0) {
          const existing = users.value[idx]
          if (existing) {
            users.value[idx] = { ...existing, ...payload, id: awarenessId }
          }
        } else {
          users.value.push({
            id: awarenessId,
            name: payload.name || awarenessId.slice(0, 4),
            color: payload.color || '#999',
            role: payload.role || 'observer',
            status: payload.status || 'online',
            cursor: payload.cursor,
            permissions: payload.permissions,
          })
        }
        break
      }
      case 'chat_message': {
        const payload = message.payload as { id?: string; content?: string; timestamp?: number }
        // Deduplicate: skip if this is our own message echoing back from the server.
        // The server broadcasts chat to ALL clients (including sender), and we
        // already pushed optimistically in sendChatMessage.
        if (message.userId === options.userId && payload.id) {
          break
        }
        chatMessages.value.push({
          userId: message.userId,
          content: payload.content || '',
          timestamp: payload.timestamp || Date.now(),
        })
        break
      }
      case 'permission_change': {
        const payload = message.payload as { userId?: string; permissions?: PermissionMatrix }
        if (payload.userId === options.userId && payload.permissions) {
          permissions.value = payload.permissions
        }
        const idx = users.value.findIndex((u) => u.id === payload.userId)
        const existing = idx >= 0 ? users.value[idx] : null
        if (existing && payload.permissions) {
          users.value[idx] = { ...existing, permissions: payload.permissions }
        }
        break
      }
      case 'error': {
        const payload = message.payload as { message?: string }
        error.value = payload.message || 'unknown error'
        break
      }
      case 'file_diff': {
        const payload = message.payload as { operation?: string; path?: string; timestamp?: number; oldPath?: string; newPath?: string }
        const diffPath = payload.path || ''
        const operation = payload.operation || 'write'

        // Skip applying our own file_diff (optimistic update already done in sendFileDiff)
        if (message.userId === options.userId) break

        fileDiffs.value.push({
          userId: message.userId,
          operation,
          path: diffPath,
          timestamp: payload.timestamp || Date.now(),
        })

        // Apply to editor: reload, close, or update path
        import('@/stores/editor').then(({ useEditorStore }) => {
          const editorStore = useEditorStore()
          const currentPath = editorStore.openFilePath
          if (!currentPath) return

          const normCurrent = currentPath.replace(/\\/g, '/')

          if (operation === 'rename' && payload.oldPath && payload.newPath) {
            const normOld = payload.oldPath.replace(/\\/g, '/')
            if (normCurrent === normOld || normCurrent.endsWith(normOld)) {
              editorStore.openFile(payload.newPath)
            }
          } else if (operation === 'delete') {
            const normDiff = diffPath.replace(/\\/g, '/')
            if (normCurrent.endsWith(normDiff)) {
              editorStore.closeFile()
            }
          } else if (operation === 'write') {
            const normDiff = diffPath.replace(/\\/g, '/')
            if (normCurrent.endsWith(normDiff)) {
              if (editorStore.isDirty) {
                editorStore.error = 'File has been modified externally'
              } else {
                editorStore.reloadCurrentFile()
              }
            }
          }
        })

        // Notify FileTree to refresh via window event
        window.dispatchEvent(new CustomEvent('collab-file-diff', {
          detail: { path: diffPath, operation }
        }))
        break
      }
      case 'room_info': {
        const payload = message.payload as { projectPath?: string; projectName?: string }
        if (payload.projectPath) {
          import('@/stores/projects').then(({ useProjectsStore }) => {
            const projectsStore = useProjectsStore()
            projectsStore.injectVirtualProject(
              options.roomId,
              payload.projectPath!,
              payload.projectName || 'Collab Project',
            )
          })
        }
        break
      }
      case 'room_closed': {
        // The host closed the room; disconnect and reset the local session.
        import('@/stores/community').then(({ useCommunityStore }) => {
          const communityStore = useCommunityStore()
          communityStore.resetSession()
        })
        disconnect()
        break
      }
    }
  }

  // ── Outgoing message helpers ────────────────────────────────

  /** Send a 0xF0-prefixed custom message through the WebSocket. */
  function sendCustomMessage(payload: Record<string, unknown>) {
    const ws = provider.ws
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(encodeCustomMessage(payload))
  }

  function updateCursor(cursor: CollaborationCursor) {
    sendCustomMessage({
      type: 'awareness_update',
      roomId: options.roomId,
      userId: options.userId,
      payload: { id: options.userId, cursor },
      timestamp: Date.now(),
    })
  }

  function sendChatMessage(content: string) {
    const msgId = `${options.userId}-${Date.now()}`
    const payload = {
      type: 'chat_message',
      roomId: options.roomId,
      userId: options.userId,
      payload: { id: msgId, content, timestamp: Date.now() },
      timestamp: Date.now(),
    }
    sendCustomMessage(payload)
    // Optimistic local echo so the sender sees the bubble immediately.
    // The server also broadcasts back a copy; handleMessage deduplicates
    // on payload.id so we don't get double bubbles.
    chatMessages.value.push({
      userId: options.userId,
      content,
      timestamp: Date.now(),
    })
  }

  function sendFileDiff(path: string, content: string, operation: 'write' | 'delete' | 'rename' = 'write', extra?: { oldPath?: string; newPath?: string }) {
    const diffPayload: Record<string, unknown> = { path, operation, timestamp: Date.now() }
    if (operation === 'write') {
      diffPayload.content = content
    } else if (operation === 'delete') {
      diffPayload.delete = true
    } else if (operation === 'rename' && extra) {
      diffPayload.oldPath = extra.oldPath
      diffPayload.newPath = extra.newPath
    }
    sendCustomMessage({
      type: 'file_diff',
      roomId: options.roomId,
      userId: options.userId,
      payload: diffPayload,
      timestamp: Date.now(),
    })
    // Optimistic local update
    fileDiffs.value.push({
      userId: options.userId,
      operation,
      path,
      timestamp: Date.now(),
    })
  }

  function connect() {
    if (provider.ws && provider.ws.readyState === WebSocket.OPEN) return
    provider.connect()
  }

  function disconnect() {
    import('@/stores/projects').then(({ useProjectsStore }) => {
      const projectsStore = useProjectsStore()
      projectsStore.removeVirtualProject(options.roomId)
    })
    provider.disconnect()
    doc.destroy()
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    provider,
    doc,
    awareness,
    status,
    users,
    onlineUsers,
    chatMessages,
    permissions,
    error,
    currentUser,
    connect,
    disconnect,
    updateCursor,
    sendChatMessage,
    sendFileDiff,
  }
}
