import type {
  CollaborationRoom,
  CollaborationUser,
  CollaborationRole,
  PermissionMatrix,
} from '@/types'

const API_PREFIX = '/api/community'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_PREFIX}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json()
  if (!data.ok) {
    throw new Error(data.error || 'request failed')
  }
  return data
}

export interface CreateRoomPayload {
  name: string
  projectId?: string
  maxUsers?: number
  defaultRole?: CollaborationRole
  hostAddress?: string
  userName?: string
}

export interface JoinRoomPayload {
  inviteCode: string
  userName?: string
}

export interface JoinRoomResult {
  user: CollaborationUser
  token: string
  wsUrl: string
  roomState: {
    users: CollaborationUser[]
    permissions: PermissionMatrix
  }
}

export function createRoom(payload: CreateRoomPayload) {
  return request<{
    room: CollaborationRoom
    inviteCode: string
    user?: CollaborationUser
    token?: string
    wsUrl?: string
  }>('/rooms', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listRooms() {
  return request<{ rooms: CollaborationRoom[] }>('/rooms')
}

export function getRoom(roomId: string) {
  return request<{ room: CollaborationRoom; users: CollaborationUser[]; permissions: Record<string, PermissionMatrix> }>(
    `/rooms/${roomId}`,
  )
}

export function updateRoom(roomId: string, patch: Partial<CollaborationRoom>) {
  return request<{ room: CollaborationRoom }>(`/rooms/${roomId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function closeRoom(roomId: string) {
  return request<{ success: boolean }>(`/rooms/${roomId}`, { method: 'DELETE' })
}

export function joinRoom(roomId: string, payload: JoinRoomPayload) {
  return request<JoinRoomResult>(`/rooms/${roomId}/join`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function leaveRoom(roomId: string, userId: string) {
  return request<{ success: boolean }>(`/rooms/${roomId}/leave`, {
    method: 'POST',
    body: JSON.stringify({ userId }),
  })
}

export function getRoomUsers(roomId: string) {
  return request<{ users: CollaborationUser[] }>(`/rooms/${roomId}/users`)
}

export function updateUser(
  roomId: string,
  userId: string,
  updates: { role?: CollaborationRole; permissions?: Partial<PermissionMatrix> },
) {
  return request<{ user: CollaborationUser }>(`/rooms/${roomId}/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  })
}

export function removeUser(roomId: string, userId: string) {
  return request<{ success: boolean }>(`/rooms/${roomId}/users/${userId}`, { method: 'DELETE' })
}

export function generateInviteCode(roomId: string) {
  return request<{ inviteCode: string }>(`/rooms/${roomId}/invite`, { method: 'POST' })
}

export function getWsUrl(roomId: string, token: string) {
  return request<{ wsUrl: string }>(`/rooms/${roomId}/ws-url?token=${encodeURIComponent(token)}`)
}
