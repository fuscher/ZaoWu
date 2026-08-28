/**
 * S13-P2-1: 前端 SSE 解析单测（与 S13-P1-3 后端 serialize_event 互为护栏）。
 *
 * mock fetch 返回构造的 SSE 文本序列，驱动 sendAgentMessageStream，
 * 断言 9 类事件回调参数（契约类 bug 护栏）。
 * 覆盖事件：delta / done / tool_call_start / requires_confirmation /
 * tool_call_end / error / phase / tool_part / notice。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import type { AgentStreamCallbacks } from '@/types'
import { sendAgentMessageStream } from '@/services/ai'

function makeSSE(events: unknown[]): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')
}

/** mock fetch 返回单块 SSE 文本（一次性 enqueue 后 close）。 */
function stubFetchSSE(events: unknown[]) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(makeSSE(events)))
      controller.close()
    },
  })
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: stream,
      json: async () => ({}),
    })
  )
}

function makeCallbacks(
  overrides: Partial<AgentStreamCallbacks> = {}
): Required<Pick<AgentStreamCallbacks, 'onDelta' | 'onToolCallStart' | 'onRequiresConfirmation' | 'onToolCallEnd' | 'onDone' | 'onError'>> &
  Pick<AgentStreamCallbacks, 'onPhase' | 'onToolPart' | 'onNotice' | 'onErrorPayload'> {
  return {
    onDelta: vi.fn(),
    onToolCallStart: vi.fn(),
    onRequiresConfirmation: vi.fn(),
    onToolCallEnd: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
    onErrorPayload: vi.fn(),
    onPhase: vi.fn(),
    onToolPart: vi.fn(),
    onNotice: vi.fn(),
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('S13-P2-1: sendAgentMessageStream SSE 事件解析', () => {
  it('delta → onDelta(id, delta)', async () => {
    stubFetchSSE([{ id: 'm1', type: 'delta', delta: '你好', done: false }])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onDelta).toHaveBeenCalledWith('m1', '你好')
  })

  it('done → onDone(id, content, {quality, summary, phase_history, recovery})', async () => {
    stubFetchSSE([
      {
        id: 'm1', type: 'done', content: '完成', done: true,
        quality: 'constrained', summary: '计划模式',
        phase_history: ['thinking', 'tool', 'done'],
        recovery: [{ label: '切换到执行模式并继续', action: 'switch_preset:build' }],
      },
    ])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onDone).toHaveBeenCalledWith(
      'm1',
      '完成',
      {
        quality: 'constrained',
        summary: '计划模式',
        phase_history: ['thinking', 'tool', 'done'],
        recovery: [{ label: '切换到执行模式并继续', action: 'switch_preset:build' }],
      }
    )
  })

  it('done（无附带字段）→ onDone 携带空对象兜底', async () => {
    stubFetchSSE([{ id: 'm1', type: 'done', content: 'ok', done: true }])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onDone).toHaveBeenCalledWith('m1', 'ok', {
      quality: undefined,
      summary: undefined,
      phase_history: undefined,
      recovery: undefined,
    })
  })

  it('tool_call_start → onToolCallStart(id, toolCall)', async () => {
    const toolCall = { requestId: 'r1', name: 'read_file', arguments: { path: 'a.py' } }
    stubFetchSSE([{ id: 'm1', type: 'tool_call_start', toolCall }])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onToolCallStart).toHaveBeenCalledWith('m1', toolCall)
  })

  it('requires_confirmation → onRequiresConfirmation(id, toolCall)', async () => {
    const toolCall = { requestId: 'r2', name: 'write_file', arguments: { path: 'b.py' } }
    stubFetchSSE([{ id: 'm1', type: 'requires_confirmation', toolCall }])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onRequiresConfirmation).toHaveBeenCalledWith('m1', toolCall)
  })

  it('tool_call_end → onToolCallEnd(id, toolResult)', async () => {
    const toolResult = { requestId: 'r1', success: true, content: 'ok' }
    stubFetchSSE([{ id: 'm1', type: 'tool_call_end', toolResult }])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onToolCallEnd).toHaveBeenCalledWith('m1', toolResult)
  })

  it('error → onError(message) + onErrorPayload(id, payload)', async () => {
    stubFetchSSE([
      {
        id: 'err1', type: 'error', code: 'llm_auth', message: 'API 鉴权失败',
        kind: 'provider', traceId: 'trace-1',
        recovery: [{ label: '重试', action: 'retry' }],
      },
    ])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onError).toHaveBeenCalledWith('API 鉴权失败')
    expect(cb.onErrorPayload).toHaveBeenCalledWith('err1', {
      code: 'llm_auth',
      message: 'API 鉴权失败',
      kind: 'provider',
      traceId: 'trace-1',
      recovery: [{ label: '重试', action: 'retry' }],
    })
  })

  it('phase → onPhase(id, phase, detail, ts)', async () => {
    stubFetchSSE([
      { id: 'm1', type: 'phase', phase: 'compacting', detail: '预算触发主动压缩', ts: 123 },
    ])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onPhase).toHaveBeenCalledWith('m1', 'compacting', '预算触发主动压缩', 123)
  })

  it('phase（无 detail/ts）→ onPhase 携带 undefined', async () => {
    stubFetchSSE([{ id: 'm1', type: 'phase', phase: 'thinking' }])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onPhase).toHaveBeenCalledWith('m1', 'thinking', undefined, undefined)
  })

  it('tool_part → onToolPart(id, {requestId, part, reason, ts})', async () => {
    stubFetchSSE([
      { id: 'm1', type: 'tool_part', requestId: 'r1', part: 'denied', reason: 'plan_mode_readonly', ts: 456 },
    ])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onToolPart).toHaveBeenCalledWith('m1', {
      requestId: 'r1',
      part: 'denied',
      reason: 'plan_mode_readonly',
      ts: 456,
    })
  })

  it('notice → onNotice(id, {level, code, message, recoverable, ts})', async () => {
    stubFetchSSE([
      {
        id: 'system', type: 'notice', level: 'warn', code: 'compacted',
        message: '已自动压缩早期对话', recoverable: true, ts: 789,
      },
    ])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onNotice).toHaveBeenCalledWith('system', {
      level: 'warn',
      code: 'compacted',
      message: '已自动压缩早期对话',
      recoverable: true,
      ts: 789,
    })
  })

  it('9 类事件同流解析互不干扰', async () => {
    const toolCall = { requestId: 'r1', name: 'read_file', arguments: {} }
    stubFetchSSE([
      { id: 'm1', type: 'delta', delta: '思考', done: false },
      { id: 'm1', type: 'tool_call_start', toolCall },
      { id: 'm1', type: 'phase', phase: 'tool', ts: 1 },
      { id: 'm1', type: 'tool_call_end', toolResult: { requestId: 'r1', success: true, content: 'x' } },
      { id: 'm1', type: 'done', content: '完成', done: true, quality: 'success' },
    ])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onDelta).toHaveBeenCalledTimes(1)
    expect(cb.onToolCallStart).toHaveBeenCalledTimes(1)
    expect(cb.onPhase).toHaveBeenCalledTimes(1)
    expect(cb.onToolCallEnd).toHaveBeenCalledTimes(1)
    expect(cb.onDone).toHaveBeenCalledTimes(1)
  })

  it('非 data: 行与损坏 JSON 被跳过（不抛错）', async () => {
    stubFetchSSE([
      'event: custom\n',
      'data: {bad json\n\n',
      { id: 'm1', type: 'delta', delta: 'ok', done: false },
    ] as unknown as object[])
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onDelta).toHaveBeenCalledWith('m1', 'ok')
    expect(cb.onError).not.toHaveBeenCalled()
  })

  it('HTTP 非 2xx → onError(err.error || HTTP status)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: async () => ({ error: 'maxIterations must be an integer' }),
      })
    )
    const cb = makeCallbacks()
    await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(cb.onError).toHaveBeenCalledWith('maxIterations must be an integer')
  })

  it('流读取异常 → onError(message) 且返回 AbortController', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        get body() {
          throw new Error('stream broken')
        },
        json: async () => ({}),
      })
    )
    const cb = makeCallbacks()
    const controller = await sendAgentMessageStream('conv-1', 'hi', cb)
    expect(controller).toBeInstanceOf(AbortController)
    expect(cb.onError).toHaveBeenCalled()
  })
})
