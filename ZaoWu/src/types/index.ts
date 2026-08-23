export type Theme = 'dark' | 'light'

export type ViewType = 'chat' | 'files' | 'search' | 'git' | 'plugins' | 'community' | 'settings' | 'workflow'

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
  hostUserId?: string
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
  | 'room_closed'
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
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  timestamp: number
  model?: string
  tokens?: number
  tool_calls?: Array<{
    id: string
    type: string
    function: { name: string; arguments: string }
  }>
  tool_call_id?: string
  name?: string
  /** 智能体消息元数据（阶段 A6）：完成质量 / 错误码，驱动分级渲染 */
  metadata?: MessageMetadata
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
  maxTokens?: number
  /** P0-4: 上下文压缩预算（可到 1M），回退 maxTokens */
  contextBudget?: number
  /** P0-4: LLM 生成上限（钳 131072），独立于压缩预算 */
  maxGenerationTokens?: number
  agentConfig?: AgentConfig
}

export type ProviderProtocol = 'openai' | 'anthropic'

export type ProviderAuthType = 'bearer' | 'x-api-key' | 'none'

export interface LLMProvider {
  id: string
  name: string
  apiBase: string
  apiKey: string
  models: LLMModel[]
  /** 预设来源标记（'custom' 表示自定义供应商） */
  presetId?: string
  /** 请求协议：openai=OpenAI 兼容 /chat/completions；anthropic=Messages API */
  protocol?: ProviderProtocol
  /** 鉴权方式：bearer（默认）/ x-api-key / none */
  authType?: ProviderAuthType
  /** 自定义请求路径（含协议内路径），默认按协议推导 */
  chatPath?: string
}

export interface LLMModel {
  /** 请求 ID：实际调用时写入 payload.model */
  id: string
  /** 显示名称：界面展示用；缺省回退 id */
  name: string
  contextLength?: number
}

/** 内置主流供应商预设（后端 /chat/provider-presets 下发） */
export interface LLMProviderPreset {
  id: string
  name: string
  apiBase: string
  protocol?: ProviderProtocol
  authType?: ProviderAuthType
  chatPath?: string
  /** 获取 API Key 的官方地址 */
  docsUrl?: string
  /** 常见模型提示 */
  modelHint?: string[]
}

export interface LLMConfig {
  defaultProviderId: string
  defaultModelId: string
  temperature: number
  maxTokens: number
  /** true = 自动从模型 contextLength 取值（默认）；false = 手动使用 maxTokens */
  maxTokensAuto?: boolean
  /** P0-4: 上下文压缩预算，回退 maxTokens */
  contextBudget?: number
  /** P0-4: LLM 生成上限，独立于压缩预算 */
  maxGenerationTokens?: number
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
  startupView: ViewType
  searchMaxFileSizeKB: number
  searchResultLimit: number
  communityMaxUsers: number
  communityDefaultRole: string
  communityFileSizeLimitKB: number
  communityInactiveTimeoutMinutes: number
  autoCheckUpdates: boolean
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
  /** Host address for virtual collaboration projects (e.g. "192.168.1.5:8080"). */
  hostAddress?: string
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

export type GitChangeType = 'untracked' | 'modified' | 'added' | 'deleted' | 'renamed' | 'conflict'

export type GitChangeStatus = 'untracked' | 'unstaged' | 'staged' | 'conflict'

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
        save_file_dialog: (defaultFilename: string) => Promise<string | null>
      }
    }
    __SETTINGS__?: Record<string, unknown>
  }
}

// ── Stage 8: Agent types ─────────────────────────────────────

export interface ToolCall {
  requestId: string
  name: string
  arguments: Record<string, unknown>
}

export interface ToolResult {
  requestId: string
  success: boolean
  content: string
  error?: string
  tool: string
}

/** 完成质量（阶段 A4/B）：驱动气泡分级渲染。success=正常；idle=说而不做；
 * constrained=模式约束致空；empty=真空响应；stopped=用户停止/循环中断；
 * error_fallback=错误终态（挂 ErrorCard）；incomplete=轮次耗尽未收敛。 */
export type MessageQuality =
  | 'success'
  | 'idle'
  | 'constrained'
  | 'empty'
  | 'stopped'
  | 'error_fallback'
  | 'incomplete'

/** 智能体消息元数据（阶段 A6，落库 messages.metadata_json） */
export interface MessageMetadata {
  quality?: MessageQuality
  phase_history?: string[]
  error_code?: string
  error_message?: string
  error_trace_id?: string
  /** 错误事件的 recovery CTA（阶段 D 修复：历史/终态错误 ErrorCard 需从 metadata 恢复） */
  error_recovery?: RecoveryAction[]
}

/** phase 阶段枚举（阶段 C2，对齐 master §5.1） */
export type PhaseName =
  | 'thinking'
  | 'tool'
  | 'compacting'
  | 'retrying'
  | 'handoff'
  | 'done'

/** PhaseStrip 节点：每轮/状态切换的 phase 事件（含挂载其下的 notice 子节点） */
export interface PhaseNode {
  phase: PhaseName
  detail?: string
  ts: number
  notices?: NoticePayload[]
}

/** tool_part 生命周期节点（阶段 C2，对齐 master §5.2） */
export interface ToolPartState {
  requestId: string
  part:
    | 'generating'
    | 'permission_pending'
    | 'running'
    | 'success'
    | 'denied'
    | 'failed'
  reason?: string
  ts: number
}

/** notice 系统提示（阶段 C2，对齐 master §5.3） */
export interface NoticePayload {
  level: 'info' | 'warn' | 'blocked'
  code: string
  message: string
  recoverable?: boolean
  ts: number
}

/** 错误终态 payload（阶段 C2，对齐 master §5.4） */
export interface ErrorPayload {
  code: string
  message: string
  kind?: string
  traceId?: string
  recovery?: RecoveryAction[]
}

/** 恢复 CTA：label 前端展示，action 走 recoveryActions 注册表 */
export interface RecoveryAction {
  label: string
  action: string
}

export interface AgentStreamCallbacks {
  onDelta: (messageId: string, delta: string) => void
  onToolCallStart: (messageId: string, toolCall: ToolCall) => void
  onRequiresConfirmation: (messageId: string, toolCall: ToolCall) => void
  onToolCallEnd: (messageId: string, result: ToolResult) => void
  onDone: (
    messageId: string,
    fullContent: string,
    extra?: DoneExtra
  ) => void
  onError: (error: string) => void
  // ── 阶段 C：结构化事件回调（对齐 master §5）──
  onPhase?: (messageId: string, phase: PhaseName, detail?: string, ts?: number) => void
  onToolPart?: (messageId: string, part: ToolPartState) => void
  onNotice?: (messageId: string, notice: NoticePayload) => void
  /** 结构化错误：与 onError(string) 共存，ErrorCard 消费 payload */
  onErrorPayload?: (messageId: string, payload: ErrorPayload) => void
}

export interface AgentConfig {
  enabled?: boolean
  systemPrompt?: string
  maxIterations?: number
  projectPath?: string
  requiresApproval?: boolean
  /** @deprecated 技能改为「全部启用即生效」，此字段已忽略，不再读写 */
  selectedSkill?: string
  skillConfig?: Record<string, Record<string, any>>
  autoApproveWrites?: boolean
  /** 智能体预设模式：build=默认（全工具）；plan=只读规划（写工具被 deny） */
  preset?: 'build' | 'plan'
}

export interface Skill {
  name: string
  description: string
  tags: string[]
  source: 'builtin' | string
  enabled: boolean
  defaultConfig?: Record<string, any>
  allowedTools?: string[]
}

/** done 事件附带字段（对齐 master §5.5：quality/summary/phase_history/recovery） */
export interface DoneExtra {
  quality?: MessageQuality
  summary?: string
  /** 本轮 phase 节点链（历史消息 PhaseStrip 恢复用） */
  phase_history?: string[]
  /** 恢复 CTA（constrained 交接等场景，由后端 _done_event 发送） */
  recovery?: RecoveryAction[]
}

export type SSEEvent =
  | { id: string; type: 'delta'; delta: string; done: false }
  | { id: string; type: 'tool_call_start'; toolCall: ToolCall }
  | { id: string; type: 'requires_confirmation'; toolCall: ToolCall }
  | { id: string; type: 'tool_call_end'; toolResult: ToolResult }
  | { id: string; type: 'done'; content: string; done: true; quality?: MessageQuality; summary?: string; phase_history?: string[]; recovery?: RecoveryAction[] }
  | { id: string; type: 'error'; code: string; message: string; kind?: string; traceId?: string; recovery?: RecoveryAction[] }
  // ── 阶段 C：结构化事件（对齐 master §5）──
  | { id: string; type: 'phase'; phase: PhaseName; detail?: string; ts?: number }
  | { id: string; type: 'tool_part'; requestId: string; part: ToolPartState['part']; reason?: string; ts?: number }
  | { id: string; type: 'notice'; level: NoticePayload['level']; code: string; message: string; recoverable?: boolean; ts?: number }
