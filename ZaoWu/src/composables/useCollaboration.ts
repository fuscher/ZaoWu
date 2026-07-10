import { ref, computed, watch, onUnmounted } from 'vue'
import * as Y from 'yjs'
import { YjsProvider } from '@/services/yjsProvider'
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
  userName: string
  userColor: string
}

export function useCollaboration(options: UseCollaborationOptions) {
  const status = ref<'connecting' | 'connected' | 'disconnected' | 'reconnecting' | 'error'>('disconnected')
  const synced = ref(false)
  const users = ref<CollaborationUser[]>([])
  const chatMessages = ref<{ userId: string; content: string; timestamp: number }[]>([])
  const fileDiffs = ref<{ userId: string; operation: string; path: string; timestamp: number }[]>([])
  const permissions = ref<PermissionMatrix | null>(null)
  const error = ref('')

  const provider = new YjsProvider({
    roomId: options.roomId,
    wsUrl: options.wsUrl,
    userId: options.userId,
    onMessage: handleMessage,
    onStatusChange: (s) => {
      status.value = s
      if (s === 'connected') {
        error.value = ''
        publishAwareness()
      }
    },
    onSync: (s) => {
      synced.value = s
    },
  })

  const currentUser = computed<CollaborationUser>(() => ({
    id: options.userId,
    name: options.userName,
    color: options.userColor,
    role: permissions.value ? (permissions.value.kick ? 'host' : permissions.value.edit ? 'collaborator' : 'observer') : 'collaborator',
    status: status.value === 'connected' ? 'online' : 'offline',
    permissions: permissions.value || undefined,
  }))

  const onlineUsers = computed(() =>
    [currentUser.value, ...users.value].filter((u) => u.status === 'online'),
  )

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
        const payload = message.payload as { content?: string; timestamp?: number }
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
        const payload = message.payload as { operation?: string; path?: string; timestamp?: number }
        fileDiffs.value.push({
          userId: message.userId,
          operation: payload.operation || 'write',
          path: payload.path || '',
          timestamp: payload.timestamp || Date.now(),
        })
        break
      }
    }
  }

  function publishAwareness() {
    const awarenessPayload = {
      id: options.userId,
      name: options.userName,
      color: options.userColor,
      status: 'online',
    }
    provider.send('awareness_update', awarenessPayload)
  }

  function updateCursor(cursor: CollaborationCursor) {
    provider.send('awareness_update', {
      id: options.userId,
      cursor,
    })
  }

  function sendChatMessage(content: string) {
    provider.send('chat_message', {
      id: `${options.userId}-${Date.now()}`,
      content,
      timestamp: Date.now(),
    })
    chatMessages.value.push({
      userId: options.userId,
      content,
      timestamp: Date.now(),
    })
  }

  function sendFileDiff(path: string, content: string, operation: 'write' | 'delete' = 'write') {
    const payload: Record<string, unknown> = { path, operation, timestamp: Date.now() }
    if (operation === 'write') {
      payload.content = content
    }
    provider.send('file_diff', payload)
    fileDiffs.value.push({
      userId: options.userId,
      operation,
      path,
      timestamp: Date.now(),
    })
  }

  function connect() {
    provider.connect()
  }

  function disconnect() {
    provider.disconnect()
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    provider,
    doc: provider.doc,
    awareness: provider.awareness,
    status,
    synced,
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
