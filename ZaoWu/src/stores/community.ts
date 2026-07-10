import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import * as communityApi from '@/services/community'
import type {
  CollaborationRoom,
  CollaborationUser,
  CollaborationRole,
  PermissionMatrix,
  ConnectionStatus,
} from '@/types'

export const useCommunityStore = defineStore('community', () => {
  // Rooms
  const rooms = ref<CollaborationRoom[]>([])
  const currentRoom = ref<CollaborationRoom | null>(null)

  // Current session
  const currentUser = ref<CollaborationUser | null>(null)
  const token = ref<string>('')
  const wsUrl = ref<string>('')

  // Connection / users
  const connectionStatus = ref<ConnectionStatus>('disconnected')
  const users = ref<CollaborationUser[]>([])
  const error = ref('')
  const inviteCode = ref('')

  const isHost = computed(() => currentUser.value?.role === 'host')
  const isInRoom = computed(() => currentRoom.value !== null)

  const canEdit = computed(() => {
    if (!currentUser.value?.permissions) return false
    return currentUser.value.permissions.edit
  })

  const canInvite = computed(() => {
    if (!currentUser.value?.permissions) return false
    return currentUser.value.permissions.invite
  })

  const canKick = computed(() => {
    if (!currentUser.value?.permissions) return false
    return currentUser.value.permissions.kick
  })

  async function loadRooms() {
    try {
      const data = await communityApi.listRooms()
      rooms.value = data.rooms.filter((r) => r.status === 'active')
      error.value = ''
    } catch (err) {
      error.value = String(err)
    }
  }

  async function createRoom(
    name: string,
    projectId: string,
    options?: { maxUsers?: number; defaultRole?: CollaborationRole; hostAddress?: string; userName?: string },
  ) {
    try {
      const data = await communityApi.createRoom({
        name,
        projectId,
        maxUsers: options?.maxUsers,
        defaultRole: options?.defaultRole,
        hostAddress: options?.hostAddress,
        userName: options?.userName,
      })
      currentRoom.value = data.room
      inviteCode.value = data.inviteCode
      // Host auto-joined by backend — store the credentials
      if (data.user) {
        currentUser.value = data.user
        token.value = data.token ?? ''
        wsUrl.value = data.wsUrl ?? ''
      }
      rooms.value.unshift(data.room)
      error.value = ''
      return data
    } catch (err) {
      error.value = String(err)
      throw err
    }
  }

  async function joinRoom(roomId: string, inviteCode: string, userName: string) {
    try {
      const data = await communityApi.joinRoom(roomId, { inviteCode, userName })
      currentUser.value = data.user
      token.value = data.token
      wsUrl.value = data.wsUrl
      users.value = data.roomState.users
      error.value = ''
      return data
    } catch (err) {
      error.value = String(err)
      throw err
    }
  }

  async function leaveRoom() {
    if (currentRoom.value && currentUser.value) {
      try {
        await communityApi.leaveRoom(currentRoom.value.id, currentUser.value.id)
      } catch {
        // ignore
      }
    }
    resetSession()
  }

  async function closeRoom(roomId: string) {
    try {
      await communityApi.closeRoom(roomId)
      rooms.value = rooms.value.filter((r) => r.id !== roomId)
      if (currentRoom.value?.id === roomId) {
        resetSession()
      }
      error.value = ''
    } catch (err) {
      error.value = String(err)
      throw err
    }
  }

  async function updateUserRole(userId: string, role: CollaborationRole, permissions?: Partial<PermissionMatrix>) {
    if (!currentRoom.value) return
    try {
      const data = await communityApi.updateUser(currentRoom.value.id, userId, { role, permissions })
      const idx = users.value.findIndex((u) => u.id === userId)
      if (idx >= 0) {
        users.value[idx] = data.user
      }
      error.value = ''
      return data.user
    } catch (err) {
      error.value = String(err)
      throw err
    }
  }

  async function removeUser(userId: string) {
    if (!currentRoom.value) return
    try {
      await communityApi.removeUser(currentRoom.value.id, userId)
      users.value = users.value.filter((u) => u.id !== userId)
      error.value = ''
    } catch (err) {
      error.value = String(err)
      throw err
    }
  }

  async function refreshInviteCode() {
    if (!currentRoom.value) return
    try {
      const data = await communityApi.generateInviteCode(currentRoom.value.id)
      inviteCode.value = data.inviteCode
      currentRoom.value.inviteCode = data.inviteCode
      error.value = ''
      return data.inviteCode
    } catch (err) {
      error.value = String(err)
      throw err
    }
  }

  function setConnectionStatus(status: ConnectionStatus) {
    connectionStatus.value = status
  }

  function updateUsers(newUsers: CollaborationUser[]) {
    users.value = newUsers
  }

  function addUser(user: CollaborationUser) {
    const idx = users.value.findIndex((u) => u.id === user.id)
    if (idx >= 0) {
      users.value[idx] = { ...users.value[idx], ...user }
    } else {
      users.value.push(user)
    }
  }

  function removeUserLocal(userId: string) {
    users.value = users.value.filter((u) => u.id !== userId)
  }

  function resetSession() {
    currentRoom.value = null
    currentUser.value = null
    token.value = ''
    wsUrl.value = ''
    users.value = []
    connectionStatus.value = 'disconnected'
    inviteCode.value = ''
  }

  return {
    rooms,
    currentRoom,
    currentUser,
    token,
    wsUrl,
    connectionStatus,
    users,
    error,
    inviteCode,
    isHost,
    isInRoom,
    canEdit,
    canInvite,
    canKick,
    loadRooms,
    createRoom,
    joinRoom,
    leaveRoom,
    closeRoom,
    updateUserRole,
    removeUser,
    refreshInviteCode,
    setConnectionStatus,
    updateUsers,
    addUser,
    removeUserLocal,
    resetSession,
  }
})
