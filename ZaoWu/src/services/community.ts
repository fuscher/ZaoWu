import type {
  CollaborationRoom,
  CollaborationUser,
  CollaborationRole,
  PermissionMatrix,
} from '@/types'
import { apiPath } from '@/utils/api'

const API_PREFIX = apiPath('/community')

async function request<T>(path: string, options?: RequestInit & { token?: string }): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (options?.token) {
    headers.Authorization = `Bearer ${options.token}`
  }
  const res = await fetch(`${API_PREFIX}${path}`, {
    headers,
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

export function lookupRoom(code: string) {
  return request<{ room: CollaborationRoom }>(`/rooms/lookup?code=${encodeURIComponent(code)}`)
}

export function getRoom(roomId: string, token: string) {
  return request<{ room: CollaborationRoom; users: CollaborationUser[]; permissions: Record<string, PermissionMatrix> }>(
    `/rooms/${roomId}`,
    { token },
  )
}

export function updateRoom(roomId: string, patch: Partial<CollaborationRoom>, token: string) {
  return request<{ room: CollaborationRoom }>(`/rooms/${roomId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
    token,
  })
}

export function closeRoom(roomId: string, token: string) {
  return request<{ success: boolean }>(`/rooms/${roomId}`, { method: 'DELETE', token })
}

export function joinRoom(roomId: string, payload: JoinRoomPayload) {
  return request<JoinRoomResult>(`/rooms/${roomId}/join`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function leaveRoom(roomId: string, userId: string, token: string) {
  return request<{ success: boolean }>(`/rooms/${roomId}/leave`, {
    method: 'POST',
    body: JSON.stringify({ userId }),
    token,
  })
}

export function getRoomUsers(roomId: string, token: string) {
  return request<{ users: CollaborationUser[] }>(`/rooms/${roomId}/users`, { token })
}

export function updateUser(
  roomId: string,
  userId: string,
  updates: { role?: CollaborationRole; permissions?: Partial<PermissionMatrix> },
  token: string,
) {
  return request<{ user: CollaborationUser }>(`/rooms/${roomId}/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
    token,
  })
}

export function removeUser(roomId: string, userId: string, token: string) {
  return request<{ success: boolean }>(`/rooms/${roomId}/users/${userId}`, { method: 'DELETE', token })
}

export function generateInviteCode(roomId: string, token: string) {
  return request<{ inviteCode: string }>(`/rooms/${roomId}/invite`, { method: 'POST', token })
}
