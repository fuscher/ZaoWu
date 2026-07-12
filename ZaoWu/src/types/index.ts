export type Theme = 'dark' | 'light'

export type ViewType = 'chat' | 'files' | 'search' | 'git' | 'plugins' | 'community' | 'settings'

// ── Community / Collaboration types ─────────────────────────────

export type CollaborationRole = 'host' | 'collaborator' | 'observer'

export type CollaborationRoomStatus = 'active' | 'paused' | 'closed'

export type CollaborationUserStatus = 'online' | 'away' | 'offline'

export interface CollaborationCursor {
  filePath: string
  line: number
  column: number
}

export interface CollaborationRoom {
  id: string
  name: string
  projectId: string
  hostId: string
  hostAddress: string
  status: CollaborationRoomStatus
  inviteCode: string
  maxUsers: number
  createdAt: number
  updatedAt: number
}

export interface CollaborationUser {
  id: string
  name: string
  color: string
  role: CollaborationRole
  status: CollaborationUserStatus
  cursor?: CollaborationCursor
  permissions?: PermissionMatrix
}

export interface PermissionMatrix {
  edit: boolean
  chat: boolean
  terminal: boolean
  invite: boolean
  kick: boolean
  manageFiles: boolean
}

export const DEFAULT_PERMISSIONS: Record<CollaborationRole, PermissionMatrix> = {
  host: { edit: true, chat: true, terminal: true, invite: true, kick: true, manageFiles: true },
  collaborator: { edit: true, chat: true, terminal: false, invite: false, kick: false, manageFiles: false },
  observer: { edit: false, chat: true, terminal: false, invite: false, kick: false, manageFiles: false },
}

export type WSMessageType =
  | 'join_room'
  | 'leave_room'
  | 'yjs_update'
  | 'awareness_update'
  | 'chat_message'
  | 'file_diff'
  | 'user_joined'
  | 'user_left'
  | 'permission_change'
  | 'room_state'
  | 'room_info'
  | 'ping'
  | 'pong'
  | 'error'

export interface WSMessage<T = unknown> {
  type: WSMessageType
  roomId: string
  userId: string
  payload: T
  timestamp: number
}

export interface CollaborationChatMessage {
  id: string
  content: string
  timestamp: number
}

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'error'

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  model?: string
  tokens?: number
}

export interface Conversation {
  id: string
  title: string
  providerId: string
  modelId: string
  systemPrompt: string
  messages: Message[]
  createdAt: string
  updatedAt: string
  messageCount?: number
}

export interface LLMProvider {
  id: string
  name: string
  apiBase: string
  apiKey: string
  models: LLMModel[]
}

export interface LLMModel {
  id: string
  name: string
  contextLength?: number
}

export interface LLMConfig {
  defaultProviderId: string
  defaultModelId: string
  temperature: number
  maxTokens: number
  topP: number
  systemPrompt: string
}

export interface LLMPreset {
  id: string
  name: string
  systemPrompt: string
  temperature: number
  maxTokens: number
  topP: number
}

export interface ViewItem {
  id: ViewType
  label: string
  icon: string
}

export interface BackgroundSettings {
  enabled: boolean
  effect: string
  persist: boolean
  language: string
  theme: string
  searchMaxFileSizeKB: number
  searchResultLimit: number
  communityMaxUsers: number
  communityDefaultRole: string
  communityFileSizeLimitKB: number
  communityInactiveTimeoutMinutes: number
}

export interface Project {
  id: string
  path: string
  name: string
  addedAt: string
  archived: boolean
  lastModified: string | null
  virtual?: boolean
  roomId?: string
}

export interface TreeNode {
  name: string
  path: string
  type: 'file' | 'directory'
  children?: TreeNode[]
}

export interface SearchResult {
  path: string
  name: string
  matches: SearchMatch[]
}

export type SearchMatch = ContentMatch | FilenameMatch

export interface ContentMatch {
  type: 'content'
  line: number
  content: string
  startIndex: number
  endIndex: number
}

export interface FilenameMatch {
  type: 'filename'
}

export type GitAvailability = 'unchecked' | 'available' | 'unavailable'

export type GitChangeType = 'untracked' | 'modified' | 'added' | 'deleted' | 'renamed'

export type GitChangeStatus = 'unstaged' | 'staged'

export interface GitChange {
  path: string
  type: GitChangeType
  status: GitChangeStatus
  oldPath?: string
}

export interface GitBranch {
  name: string
  isCurrent: boolean
  isRemote: boolean
}

export interface GitCommit {
  hash: string
  shortHash: string
  message: string
  author: string
  date: string
  isLocalTip: boolean
  isRemoteTip: boolean
}

declare global {
  interface Window {
    pywebview?: {
      api: {
        minimize: () => void
        maximize: () => void
        restore: () => void
        move: (x: number, y: number) => void
        shutdown: () => void
        select_folder: () => Promise<string | null>
      }
    }
    __SETTINGS__?: Record<string, unknown>
  }
}
