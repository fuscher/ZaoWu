import { apiPath } from '@/utils/api'
import type { WorkflowDefinition } from '@/types/workflow'

const BASE = apiPath('/workflows')

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json()
  if (!data.ok) throw new Error(data.error || 'request failed')
  return data
}

export async function listWorkflows(): Promise<{ id: string; name: string; updatedAt: number; version: number }[]> {
  const data = await request<{ workflows: { id: string; name: string; updatedAt: number; version: number }[] }>(BASE)
  return data.workflows
}

export async function createWorkflow(definition: WorkflowDefinition): Promise<WorkflowDefinition> {
  const data = await request<{ workflow: WorkflowDefinition }>(BASE, {
    method: 'POST',
    body: JSON.stringify(definition),
  })
  return data.workflow
}

export async function fetchWorkflow(id: string): Promise<WorkflowDefinition> {
  const data = await request<{ workflow: WorkflowDefinition }>(`${BASE}/${id}`)
  return data.workflow
}

export async function updateWorkflow(id: string, definition: WorkflowDefinition): Promise<WorkflowDefinition> {
  const data = await request<{ workflow: WorkflowDefinition }>(`${BASE}/${id}`, {
    method: 'PUT',
    body: JSON.stringify(definition),
  })
  return data.workflow
}

export async function deleteWorkflow(id: string): Promise<void> {
  await request(`${BASE}/${id}`, { method: 'DELETE' })
}

export async function exportWorkflowToFile(id: string, filePath: string): Promise<void> {
  await request(`${BASE}/${id}/export`, {
    method: 'POST',
    body: JSON.stringify({ filePath }),
  })
}

export interface WorkflowEvent {
  type: string
  workflowId: string
  runId: string
  nodeId?: string
  input?: Record<string, unknown>
  output?: Record<string, unknown>
  delta?: string
  tokens?: number
  elapsedMs?: number
  error?: string
  retryAttempt?: number
  toolCall?: Record<string, unknown>
  pauseReason?: string
  totalTokens?: number
  endTime?: number
  startTime?: number
  sourceNodeId?: string
  targetNodeId?: string
}

export interface RunCallbacks {
  onEvent: (event: WorkflowEvent) => void
  onError: (error: string) => void
  onDone: () => void
}

export async function runWorkflow(
  id: string,
  initialInput: string,
  callbacks: RunCallbacks,
): Promise<AbortController> {
  const controller = new AbortController()
  try {
    const res = await fetch(`${BASE}/${id}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initialInput }),
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
          const event = JSON.parse(line.slice(6)) as WorkflowEvent
          callbacks.onEvent(event)
        } catch {
          // skip malformed lines
        }
      }
    }
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') return controller
    callbacks.onError(err instanceof Error ? err.message : 'unknown error')
  } finally {
    callbacks.onDone()
  }
  return controller
}

export async function stopWorkflow(id: string, runId: string): Promise<void> {
  try {
    await fetch(`${BASE}/${id}/run/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ runId }),
    })
  } catch {
    // ignore
  }
}

export async function confirmTool(
  id: string,
  runId: string,
  requestId: string,
  approved: boolean,
): Promise<void> {
  await request(`${BASE}/${id}/confirm-tool`, {
    method: 'POST',
    body: JSON.stringify({ runId, requestId, approved }),
  })
}

export interface RunRecord {
  runId: string
  workflowId: string
  status: 'running' | 'completed' | 'errored' | 'stopped'
  startTime: number
  endTime: number | null
  totalTokens: number
  error: string | null
  initialInput: string
}

export async function listRuns(workflowId: string): Promise<RunRecord[]> {
  const data = await request<{ runs: RunRecord[] }>(`${BASE}/${workflowId}/runs`)
  return data.runs
}
