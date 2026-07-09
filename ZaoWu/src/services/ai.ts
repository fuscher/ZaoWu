import type { LLMProvider, LLMConfig, Conversation, Message } from '@/types'

const BASE = '/api/chat'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json()
  if (!data.ok) throw new Error(data.error || 'request failed')
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
  params: Partial<Pick<Conversation, 'title' | 'providerId' | 'modelId' | 'systemPrompt'>>
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
