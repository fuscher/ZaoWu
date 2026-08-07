import type { LLMProvider, LLMConfig, Conversation, Message, AgentStreamCallbacks, SSEEvent, Skill } from '@/types'
import { apiPath } from '@/utils/api'

const BASE = apiPath('/chat')

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json()
  if (!data.ok) {
    // 暴露 HTTP 状态码供调用方区分（如 410 确认过期可重试）
    const err = new Error(data.error || 'request failed') as Error & { status: number }
    err.status = res.status
    throw err
  }
  return data
}

// ── Providers ─────────────────────────────────────────────

export async function fetchProviders(): Promise<LLMProvider[]> {
  const data = await request<{ providers: LLMProvider[] }>(`${BASE}/providers`)
  return data.providers
}

export async function saveProviders(providers: LLMProvider[]): Promise<void> {
  await request(`${BASE}/providers`, {
    method: 'POST',
    body: JSON.stringify({ providers }),
  })
}

export async function fetchModels(providerId: string): Promise<{ id: string; name: string }[]> {
  const data = await request<{ models: { id: string; name: string }[] }>(
    `${BASE}/models/${providerId}`
  )
  return data.models
}

// ── Conversations ─────────────────────────────────────────

export async function fetchConversations(): Promise<Conversation[]> {
  const data = await request<{ conversations: Conversation[] }>(`${BASE}/conversations`)
  return data.conversations
}

export async function createConversation(params: {
  title?: string
  providerId?: string
  modelId?: string
  systemPrompt?: string
}): Promise<Conversation> {
  const data = await request<{ conversation: Conversation }>(`${BASE}/conversations`, {
    method: 'POST',
    body: JSON.stringify(params),
  })
  return data.conversation
}

export async function getConversation(id: string): Promise<Conversation> {
  const data = await request<{ conversation: Conversation }>(`${BASE}/conversations/${id}`)
  return data.conversation
}

export async function updateConversation(
  id: string,
  params: Partial<Pick<Conversation, 'title' | 'providerId' | 'modelId' | 'systemPrompt' | 'agentConfig'>>
): Promise<Conversation> {
  const data = await request<{ conversation: Conversation }>(`${BASE}/conversations/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(params),
  })
  return data.conversation
}

export async function deleteConversation(id: string): Promise<void> {
  await request(`${BASE}/conversations/${id}`, { method: 'DELETE' })
}

export async function clearConversation(id: string): Promise<void> {
  await request(`${BASE}/conversations/${id}/clear`, { method: 'POST' })
}

// ── Streaming Messages ────────────────────────────────────

export interface StreamCallbacks {
  onDelta: (messageId: string, delta: string) => void
  onDone: (messageId: string, fullContent: string) => void
  onError: (error: string) => void
}

export async function sendMessageStream(
  conversationId: string,
  content: string,
  callbacks: StreamCallbacks,
  params?: { temperature?: number; maxTokens?: number; topP?: number }
): Promise<AbortController> {
  const controller = new AbortController()

  try {
    const res = await fetch(`${BASE}/conversations/${conversationId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, ...params }),
      signal: controller.signal,
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'request failed' }))
      callbacks.onError(err.error || `HTTP ${res.status}`)
      return controller
    }

    const reader = res.body?.getReader()
    if (!reader) {
      callbacks.onError('no response body')
      return controller
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const payload = JSON.parse(line.slice(6))
          if (payload.done) {
            callbacks.onDone(payload.id, payload.content)
          } else if (payload.delta) {
            callbacks.onDelta(payload.id, payload.delta)
          }
        } catch {
          // skip malformed lines
        }
      }
    }
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') return controller
    callbacks.onError(err instanceof Error ? err.message : 'unknown error')
  }

  return controller
}

export async function stopGeneration(messageId: string): Promise<void> {
  try {
    await fetch(`${BASE}/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messageId }),
    })
  } catch {
    // ignore
  }
}

// ── Agent mode (Stage 8) ────────────────────────────────────

export async function sendAgentMessageStream(
  conversationId: string,
  content: string,
  callbacks: AgentStreamCallbacks,
  params?: { temperature?: number; maxTokens?: number; topP?: number }
): Promise<AbortController> {
  const controller = new AbortController()

  try {
    const res = await fetch(`${BASE}/conversations/${conversationId}/agent-messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, ...params }),
      signal: controller.signal,
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'request failed' }))
      callbacks.onError(err.error || `HTTP ${res.status}`)
      return controller
    }

    const reader = res.body?.getReader()
    if (!reader) {
      callbacks.onError('no response body')
      return controller
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const event = JSON.parse(line.slice(6)) as SSEEvent

          if (event.type === 'done' && event.done) {
            // 阶段 A4：done 携带 quality/summary（旧后端无这些字段 → 前端按 success 兜底）
            callbacks.onDone(
              event.id,
              event.content,
              { quality: event.quality, summary: event.summary }
            )
          } else if (event.type === 'delta') {
            callbacks.onDelta(event.id, event.delta)
          } else if (event.type === 'tool_call_start' && event.toolCall) {
            callbacks.onToolCallStart(event.id, event.toolCall)
          } else if (event.type === 'requires_confirmation' && event.toolCall) {
            callbacks.onRequiresConfirmation(event.id, event.toolCall)
          } else if (event.type === 'tool_call_end' && event.toolResult) {
            callbacks.onToolCallEnd(event.id, event.toolResult)
          } else if (event.type === 'error') {
            // 阶段 A3/C：结构化错误事件 → onError 兜底渲染 + onErrorPayload 供 ErrorCard
            callbacks.onError(event.message || `请求失败: ${event.code}`)
            callbacks.onErrorPayload?.(event.id, {
              code: event.code,
              message: event.message,
              kind: event.kind,
              traceId: event.traceId,
              recovery: event.recovery,
            })
          } else if (event.type === 'phase') {
            // 阶段 C2：phase 事件驱动 PhaseStrip
            callbacks.onPhase?.(event.id, event.phase, event.detail, event.ts)
          } else if (event.type === 'tool_part' && event.requestId) {
            // 阶段 C2：tool_part 驱动 ToolCallCard 状态机
            callbacks.onToolPart?.(event.id, {
              requestId: event.requestId,
              name: event.name,
              part: event.part,
              reason: event.reason,
              ts: event.ts ?? Date.now(),
            })
          } else if (event.type === 'notice') {
            // 阶段 C2：notice 挂到 PhaseStrip 对应节点
            callbacks.onNotice?.(event.id, {
              level: event.level,
              code: event.code,
              message: event.message,
              recoverable: event.recoverable,
              ts: event.ts ?? Date.now(),
            })
          }
          // 未知 type 静默忽略（升级期兼容）
        } catch {
          // skip malformed lines
        }
      }
    }
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') return controller
    callbacks.onError(err instanceof Error ? err.message : 'unknown error')
  }

  return controller
}

export async function stopAgentGeneration(convId: string): Promise<void> {
  try {
    await fetch(`${BASE}/agent-stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ convId }),
    })
  } catch {
    // ignore
  }
}

export async function confirmToolCall(
  convId: string,
  requestId: string,
  approved: boolean,
  scope: 'once' | 'always' = 'once',
  feedback?: string,
): Promise<void> {
  const url = `${BASE}/conversations/${convId}/confirm-tool`
  const body = JSON.stringify({ requestId, approved, scope, feedback })
  // P3 方案 B：410 表示确认早于 ask 分支执行（_pending_confirmation_ids 尚未注册）。
  // 真实 UI 场景极少触发（requires_confirmation 事件到达后前端才渲染面板），
  // 但跨秒级窗口下 submit 可能早于 ask 分支，410 无重试会致确认永久丢失。短延迟重试一次。
  try {
    await request<void>(url, { method: 'POST', body })
  } catch (err) {
    if ((err as Error & { status?: number }).status === 410) {
      await new Promise((r) => setTimeout(r, 200))
      await request<void>(url, { method: 'POST', body })
      return
    }
    throw err
  }
}

// ── Skills ────────────────────────────────────────────────

const SKILLS_BASE = apiPath('/agent/skills')

export async function fetchSkills(): Promise<Skill[]> {
  const data = await request<{ skills: Skill[] }>(SKILLS_BASE)
  return data.skills
}

export async function enableSkill(name: string): Promise<void> {
  await request(`${SKILLS_BASE}/${name}/enable`, { method: 'POST' })
}

export async function disableSkill(name: string): Promise<void> {
  await request(`${SKILLS_BASE}/${name}/disable`, { method: 'POST' })
}

export async function deleteSkill(name: string): Promise<void> {
  await request(`${SKILLS_BASE}/${name}`, { method: 'DELETE' })
}

export async function importSkill(content: string): Promise<Skill> {
  const data = await request<{ skill: Skill }>(`${SKILLS_BASE}/import`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
  return data.skill
}

// ── Config ────────────────────────────────────────────────

export async function fetchConfig(): Promise<LLMConfig> {
  const data = await request<{ config: LLMConfig }>(`${BASE}/config`)
  return data.config
}

export async function saveConfig(config: Partial<LLMConfig>): Promise<LLMConfig> {
  const data = await request<{ config: LLMConfig }>(`${BASE}/config`, {
    method: 'POST',
    body: JSON.stringify(config),
  })
  return data.config
}
