/**
 * Stage 9 — F02: messageId 两级索引工具 Map 隔离测试
 *
 * 验证：
 * - toolCallsFor / toolResultsFor / pendingFor 按 messageId 隔离，不串扰
 * - clearToolMaps 清空全部 Map
 * - 不同消息的工具调用不会互相泄漏
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock @/services/ai 避免真实 HTTP 调用
vi.mock('@/services/ai', () => ({
  getConversations: vi.fn().mockResolvedValue({ ok: true, conversations: [] }),
  getConversation: vi.fn().mockResolvedValue({ ok: true, conversation: null }),
  createConversation: vi.fn().mockResolvedValue({ ok: true, conversation: {} }),
  updateConversation: vi.fn().mockResolvedValue({ ok: true }),
  sendMessage: vi.fn(),
  sendAgentMessage: vi.fn(),
  sendAgentMessageStream: vi.fn(),
  stopGeneration: vi.fn(),
  stopAgentGeneration: vi.fn(),
  loadProviders: vi.fn().mockResolvedValue({ ok: true, providers: [] }),
  loadConfig: vi.fn().mockResolvedValue({ ok: true, config: {} }),
  getSkills: vi.fn().mockResolvedValue({ ok: true, skills: [] }),
}))

import * as ai from '@/services/ai'
import { useChatStore } from '@/stores/chat'
import { useProjectsStore } from '@/stores/projects'
import type { ToolCall, ToolResult } from '@/types'

describe('F02: messageId 两级索引工具 Map', () => {
  let store: ReturnType<typeof useChatStore>

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useChatStore()
    // 初始化一个当前对话
    store.currentConversation = {
      id: 'conv-test',
      title: 'Test',
      providerId: 'p1',
      modelId: 'm1',
      systemPrompt: '',
      messages: [],
      createdAt: '',
      updatedAt: '',
      agentConfig: { enabled: true, maxIterations: 5 },
    } as any
  })

  describe('toolCallsFor / toolResultsFor / pendingFor 隔离', () => {
    it('不同 messageId 的工具调用互不串扰', () => {
      const tc1: ToolCall = { requestId: 'req-1', name: 'read_file', arguments: { path: '/a' } }
      const tc2: ToolCall = { requestId: 'req-2', name: 'write_file', arguments: { path: '/b' } }

      // 为 msg-1 和 msg-2 分别添加工具调用
      store.toolCallsByMessage.set('msg-1', new Map([['req-1', tc1]]))
      store.toolCallsByMessage.set('msg-2', new Map([['req-2', tc2]]))

      // 验证隔离
      expect(store.toolCallsFor('msg-1').get('req-1')).toEqual(tc1)
      expect(store.toolCallsFor('msg-1').get('req-2')).toBeUndefined()
      expect(store.toolCallsFor('msg-2').get('req-2')).toEqual(tc2)
      expect(store.toolCallsFor('msg-2').get('req-1')).toBeUndefined()
    })

    it('toolResultsFor 按 messageId 隔离', () => {
      const tr1: ToolResult = { requestId: 'req-1', tool: 'read_file', success: true, content: 'ok' }
      const tr2: ToolResult = { requestId: 'req-2', tool: 'write_file', success: false, content: 'err' }

      store.toolResultsByMessage.set('msg-1', new Map([['req-1', tr1]]))
      store.toolResultsByMessage.set('msg-2', new Map([['req-2', tr2]]))

      expect(store.toolResultsFor('msg-1').get('req-1')).toEqual(tr1)
      expect(store.toolResultsFor('msg-1').get('req-2')).toBeUndefined()
      expect(store.toolResultsFor('msg-2').get('req-2')).toEqual(tr2)
    })

    it('pendingFor 按 messageId 隔离', () => {
      const tc1: ToolCall = { requestId: 'req-1', name: 'write_file', arguments: {} }
      const tc2: ToolCall = { requestId: 'req-2', name: 'run_command', arguments: {} }

      store.pendingByMessage.set('msg-1', new Map([['req-1', tc1]]))
      store.pendingByMessage.set('msg-2', new Map([['req-2', tc2]]))

      expect(store.pendingFor('msg-1').has('req-1')).toBe(true)
      expect(store.pendingFor('msg-1').has('req-2')).toBe(false)
      expect(store.pendingFor('msg-2').has('req-2')).toBe(true)
    })

    it('不存在的 messageId 返回空 Map（非 undefined）', () => {
      expect(store.toolCallsFor('nonexistent')).toBeInstanceOf(Map)
      expect(store.toolCallsFor('nonexistent').size).toBe(0)
      expect(store.toolResultsFor('nonexistent')).toBeInstanceOf(Map)
      expect(store.pendingFor('nonexistent')).toBeInstanceOf(Map)
    })
  })

  describe('clearToolMaps', () => {
    it('清空全部三个 Map', () => {
      // 填充数据
      store.toolCallsByMessage.set('msg-1', new Map([['r1', {} as ToolCall]]))
      store.toolResultsByMessage.set('msg-1', new Map([['r1', {} as ToolResult]]))
      store.pendingByMessage.set('msg-1', new Map([['r1', {} as ToolCall]]))
      store.toolCallsByMessage.set('msg-2', new Map([['r2', {} as ToolCall]]))

      expect(store.toolCallsByMessage.size).toBe(2)
      expect(store.toolResultsByMessage.size).toBe(1)
      expect(store.pendingByMessage.size).toBe(1)

      store.clearToolMaps()

      expect(store.toolCallsByMessage.size).toBe(0)
      expect(store.toolResultsByMessage.size).toBe(0)
      expect(store.pendingByMessage.size).toBe(0)
    })
  })

  describe('F02 场景：历史气泡不显示当前操作文件', () => {
    it('新 Agent 消息的工具调用不会泄漏到旧消息的 Map', () => {
      // 第一轮：msg-1 的工具调用
      const tc1: ToolCall = { requestId: 'r1', name: 'read_file', arguments: { path: '/old' } }
      store.toolCallsByMessage.set('msg-1', new Map([['r1', tc1]]))

      // 第二轮：msg-2 的工具调用（不同的 requestId 和 path）
      const tc2: ToolCall = { requestId: 'r2', name: 'write_file', arguments: { path: '/new' } }
      store.toolCallsByMessage.set('msg-2', new Map([['r2', tc2]]))

      // 旧消息 msg-1 不应看到 msg-2 的工具调用
      const msg1Calls = store.toolCallsFor('msg-1')
      expect(msg1Calls.size).toBe(1)
      expect(msg1Calls.get('r1')?.arguments.path).toBe('/old')
      expect(msg1Calls.get('r2')).toBeUndefined()

      // 新消息 msg-2 不应看到 msg-1 的工具调用
      const msg2Calls = store.toolCallsFor('msg-2')
      expect(msg2Calls.size).toBe(1)
      expect(msg2Calls.get('r2')?.arguments.path).toBe('/new')
      expect(msg2Calls.get('r1')).toBeUndefined()
    })
  })

  describe('6.3.1: preset computed（plan/build 切换）', () => {
    it('默认 build（agentConfig 无 preset 时回退）', () => {
      expect(store.preset).toBe('build')
    })

    it('set plan 后更新 agentConfig 并持久化', async () => {
      const ai = await import('@/services/ai')
      vi.mocked(ai.updateConversation).mockClear()
      store.preset = 'plan'
      await new Promise((r) => setTimeout(r, 0))
      expect(store.currentConversation?.agentConfig?.preset).toBe('plan')
      expect(ai.updateConversation).toHaveBeenCalledWith('conv-test', {
        agentConfig: {
          enabled: true,
          maxIterations: 5,
          preset: 'plan',
        },
      })
    })

    it('updateConversation 失败时回退本地状态', async () => {
      const ai = await import('@/services/ai')
      store.currentConversation!.agentConfig!.preset = 'build'
      vi.mocked(ai.updateConversation).mockRejectedValueOnce(new Error('network'))
      store.preset = 'plan'
      await new Promise((r) => setTimeout(r, 0))
      // 失败回退：preset 回到 build
      expect(store.currentConversation?.agentConfig?.preset).toBe('build')
    })

    it('D 修复: setPreset 返回持久化结果（失败回退时返回 false）', async () => {
      const ai = await import('@/services/ai')
      store.currentConversation!.agentConfig!.preset = 'build'
      vi.mocked(ai.updateConversation).mockRejectedValueOnce(new Error('network'))
      const ok = await store.setPreset('plan')
      await new Promise((r) => setTimeout(r, 0))
      expect(ok).toBe(false)
      expect(store.currentConversation?.agentConfig?.preset).toBe('build')
      // 成功路径返回 true
      vi.mocked(ai.updateConversation).mockResolvedValueOnce({ ok: true })
      const ok2 = await store.setPreset('plan')
      expect(ok2).toBe(true)
      expect(store.currentConversation?.agentConfig?.preset).toBe('plan')
    })
  })

  describe('阶段 A4: done quality 写入消息 metadata', () => {
    it('onDone 携带 quality 时写入 message.metadata（驱动分级渲染）', async () => {
      const ai = await import('@/services/ai')
      // 让 sendAgentMessageStream 通过 mock 返回一个可被回调驱动的流
      let capturedCallbacks: any = null
      vi.mocked(ai.sendAgentMessageStream).mockImplementationOnce(
        async (_cid: string, _content: string, callbacks: any) => {
          capturedCallbacks = callbacks
          return new AbortController()
        }
      )

      const sendPromise = store.sendAgentMessage('检查一下')
      await new Promise((r) => setTimeout(r, 0))

      const mid = store.streamingMessageId
      expect(mid).toBeTruthy()
      capturedCallbacks.onDone('persisted-id', '模型未生成有效响应', { quality: 'empty' })
      await sendPromise

      const msg = store.currentConversation!.messages.find((m) => m.id === 'persisted-id')
      expect(msg?.content).toBe('模型未生成有效响应')
      expect(msg?.metadata?.quality).toBe('empty')
      expect(store.isStreaming).toBe(false)
    })

    it('旧 done 无 quality 时不写 metadata（向后兼容）', async () => {
      const ai = await import('@/services/ai')
      let capturedCallbacks: any = null
      vi.mocked(ai.sendAgentMessageStream).mockImplementationOnce(
        async (_cid: string, _content: string, callbacks: any) => {
          capturedCallbacks = callbacks
          return new AbortController()
        }
      )

      const sendPromise = store.sendAgentMessage('你好')
      await new Promise((r) => setTimeout(r, 0))
      capturedCallbacks.onDone('persisted-id-2', 'ok')
      await sendPromise

      const msg = store.currentConversation!.messages.find((m) => m.id === 'persisted-id-2')
      expect(msg?.content).toBe('ok')
      expect(msg?.metadata).toBeUndefined()
    })
  })

  // ── 阶段 C: 结构化事件状态（对齐 master §8.3）──────────────
  describe('阶段 C1: 结构化事件状态收集', () => {
    let capturedCallbacks: any = null

    beforeEach(() => {
      vi.mocked(ai.sendAgentMessageStream).mockImplementationOnce(
        async (_cid: string, _content: string, callbacks: any) => {
          capturedCallbacks = callbacks
          return new AbortController()
        }
      )
    })

    function phaseNodeCount() {
      return store.phaseHistoryByMessage.get('persisted-c')?.length ?? 0
    }

    it('onPhase 追加 phaseHistory；onDone 后迁移到持久化 messageId', async () => {
      const sendPromise = store.sendAgentMessage('分析一下')
      await new Promise((r) => setTimeout(r, 0))
      const mid = store.streamingMessageId!
      capturedCallbacks.onPhase(mid, 'thinking', '第1轮', 1000)
      capturedCallbacks.onPhase(mid, 'tool', undefined, 2000)
      expect(store.phaseHistoryFor(mid).map((n) => n.phase)).toEqual(['thinking', 'tool'])
      // 同一 phase 连续重复不追加
      capturedCallbacks.onPhase(mid, 'tool', undefined, 3000)
      expect(store.phaseHistoryFor(mid).length).toBe(2)

      capturedCallbacks.onDone('persisted-c', 'done', { quality: 'success' })
      await sendPromise
      // 阶段 C: phaseHistory 迁移到持久化 id，临时 id 槽清除
      expect(store.phaseHistoryFor('persisted-c').map((n) => n.phase)).toEqual(['thinking', 'tool'])
      expect(store.phaseHistoryByMessage.has(mid)).toBe(false)
    })

    it('onToolPart 记录六态生命周期', async () => {
      const sendPromise = store.sendAgentMessage('改文件')
      await new Promise((r) => setTimeout(r, 0))
      const mid = store.streamingMessageId!
      capturedCallbacks.onToolPart(mid, { requestId: 'tc-1', name: 'write_file', part: 'generating', ts: 1 })
      capturedCallbacks.onToolPart(mid, { requestId: 'tc-1', name: 'write_file', part: 'permission_pending', ts: 2 })
      capturedCallbacks.onToolPart(mid, { requestId: 'tc-1', name: 'write_file', part: 'denied', reason: 'plan_mode_readonly', ts: 3 })
      const parts = store.toolPartsFor(mid)
      expect(parts.get('tc-1')?.part).toBe('denied')
      expect(parts.get('tc-1')?.reason).toBe('plan_mode_readonly')
      await sendPromise
    })

    it('onNotice 挂到最近 phase 节点', async () => {
      const sendPromise = store.sendAgentMessage('检查')
      await new Promise((r) => setTimeout(r, 0))
      const mid = store.streamingMessageId!
      capturedCallbacks.onPhase(mid, 'compacting', undefined, 1)
      capturedCallbacks.onNotice(mid, { level: 'info', code: 'compacted', message: '已压缩', ts: 2 })
      const node = store.phaseHistoryFor(mid)[0]
      expect(node?.notices?.[0]?.code).toBe('compacted')
      await sendPromise
    })

    it('onErrorPayload 写 lastError 与 metadata', async () => {
      const sendPromise = store.sendAgentMessage('跑一下')
      await new Promise((r) => setTimeout(r, 0))
      const mid = store.streamingMessageId!
      capturedCallbacks.onErrorPayload(mid, {
        code: 'llm_auth',
        message: '鉴权失败',
        kind: 'auth',
        traceId: 'trace-1',
        recovery: [{ label: '重试', action: 'retry' }],
      })
      expect(store.lastError?.code).toBe('llm_auth')
      expect(store.lastError?.traceId).toBe('trace-1')
      // metadata 写入（onDone 之前）
      const msg = store.currentConversation!.messages.find((m) => m.id === mid)
      expect(msg?.metadata?.error_code).toBe('llm_auth')
      await sendPromise
    })

    it('D 修复: onError 不再追加 ⚠️ 正文（错误由 ErrorCard 独立渲染）', async () => {
      const sendPromise = store.sendAgentMessage('跑一下')
      await new Promise((r) => setTimeout(r, 0))
      const mid = store.streamingMessageId!
      capturedCallbacks.onError('API 鉴权失败')
      const msg = store.currentConversation!.messages.find((m) => m.id === mid)
      // 正文不被 ⚠️ 污染（持久化 content 干净）
      expect(msg?.content).not.toContain('⚠️')
      expect(msg?.content).not.toContain('API 鉴权失败')
      expect(store.error).toBe('API 鉴权失败')
      await sendPromise
    })

    it('clearAgentUXMaps 清空结构化事件状态', async () => {
      store.phaseHistoryByMessage.set('m1', [{ phase: 'thinking', ts: 1 }])
      store.toolPartsByMessage.set('m1', new Map([['r1', { requestId: 'r1', part: 'running', ts: 2 } as any]]))
      store.lastError = { code: 'timeout', message: '超时' }
      store.clearAgentUXMaps()
      expect(store.phaseHistoryByMessage.size).toBe(0)
      expect(store.toolPartsByMessage.size).toBe(0)
      expect(store.lastError).toBeNull()
    })
  })

  // ── 阶段 C10: plan→build 交接（对齐 master §8.3 constrained_cta_switches_preset_and_resends）
  describe('阶段 C10: switchToBuildAndResend', () => {
    beforeEach(() => {
      vi.mocked(ai.sendAgentMessageStream).mockImplementation(
        async (_cid: string, _content: string, _callbacks: any) => new AbortController()
      )
    })

    it('plan → 切 build + 重发执行指令', async () => {
      store.currentConversation!.agentConfig!.preset = 'plan'
      // 先加一条 user 消息作为最近用户输入
      store.currentConversation!.messages.push({
        id: 'user-1',
        role: 'user',
        content: '帮我重构 auth',
        timestamp: Date.now(),
      } as any)

      await store.switchToBuildAndResend()
      await new Promise((r) => setTimeout(r, 0))

      expect(store.currentConversation?.agentConfig?.preset).toBe('build')
      const sent = vi.mocked(ai.sendAgentMessageStream).mock.calls
      const lastContent = sent[sent.length - 1]?.[1]
      expect(lastContent).toBe('请执行上述方案')
    })

    it('已处于 build 时不重发', async () => {
      const before = vi.mocked(ai.sendAgentMessageStream).mock.calls.length
      store.currentConversation!.agentConfig!.preset = 'build'
      await store.switchToBuildAndResend()
      await new Promise((r) => setTimeout(r, 0))
      // 无新 sendAgentMessage 调用（计数不增加）
      expect(vi.mocked(ai.sendAgentMessageStream).mock.calls.length).toBe(before)
    })
  })

  // ── 阶段 C9: 恢复动作注册表（对齐 master §3.5.2 / C9 验收）──
  describe('阶段 C9: recoveryActions 注册表', () => {
    it('retry 重发最近 user message', async () => {
      vi.mocked(ai.sendAgentMessageStream).mockImplementation(
        async (_cid: string, _content: string, _callbacks: any) => new AbortController()
      )
      const { runRecoveryActions } = await import('@/utils/recoveryActions')
      store.currentConversation!.messages.push({
        id: 'user-2',
        role: 'user',
        content: '上次的问题',
        timestamp: Date.now(),
      } as any)
      runRecoveryActions([{ label: '重试', action: 'retry' }], {
        lastUserMessage: '上次的问题',
        retry: () => store.sendAgentMessage('上次的问题'),
        switchToBuild: () => {},
        openProviders: () => {},
        openModelSwitcher: () => {},
        clearMessages: () => {},
        scrollToPlan: () => {},
      })
      await new Promise((r) => setTimeout(r, 0))
      const sent = vi.mocked(ai.sendAgentMessageStream).mock.calls
      expect(sent[sent.length - 1]?.[1]).toBe('上次的问题')
    })

    it('未知 action 静默忽略（不抛异常）', async () => {
      const { runRecoveryActions, isKnownRecoveryAction } = await import('@/utils/recoveryActions')
      expect(isKnownRecoveryAction('bogus:action')).toBe(false)
      const executed = runRecoveryActions(
        [{ label: 'x', action: 'bogus:action' }],
        {
          lastUserMessage: '',
          retry: () => {},
          switchToBuild: () => {},
          openProviders: () => {},
          openModelSwitcher: () => {},
          clearMessages: () => {},
          scrollToPlan: () => {},
        }
      )
      expect(executed).toBe(0)
    })
  })

  // ── maxTokens 链路：createNewConversation 透传 ─────────────
  describe('maxTokens 链路', () => {
    it('createNewConversation 携带 maxTokens 透传给后端', async () => {
      const ai = await import('@/services/ai')
      vi.mocked(ai.createConversation).mockClear()
      vi.mocked(ai.createConversation).mockResolvedValueOnce({
        id: 'new-1',
        title: '新对话',
        providerId: 'p1',
        modelId: 'm1',
        systemPrompt: '',
        messages: [],
        createdAt: '',
        updatedAt: '',
        maxTokens: 8192,
      } as any)

      const conv = await store.createNewConversation({ providerId: 'p1', modelId: 'm1', maxTokens: 8192 })
      expect(conv?.id).toBe('new-1')
      expect(ai.createConversation).toHaveBeenCalledWith(
        expect.objectContaining({ maxTokens: 8192 })
      )
    })

    it('createNewConversation 不传 maxTokens 时该字段为 undefined', async () => {
      const ai = await import('@/services/ai')
      vi.mocked(ai.createConversation).mockClear()
      vi.mocked(ai.createConversation).mockResolvedValueOnce({
        id: 'new-2',
        title: '新对话',
        providerId: 'p1',
        modelId: 'm1',
        systemPrompt: '',
        messages: [],
        createdAt: '',
        updatedAt: '',
      } as any)

      await store.createNewConversation({ providerId: 'p1', modelId: 'm1' })
      const arg = vi.mocked(ai.createConversation).mock.calls[0][0] as Record<string, unknown>
      // JSON.stringify 序列化时丢弃 undefined，后端收不到该字段
      expect(arg.maxTokens).toBeUndefined()
    })
  })

  // ── S14-P0-1: sandboxProject 绑定（对话级 projectPath）──────
  describe('S14: sandboxProject 对话↔项目绑定', () => {
    let store: ReturnType<typeof useChatStore>

    beforeEach(() => {
      setActivePinia(createPinia())
      store = useChatStore()
      store.currentConversation = {
        id: 'conv-sandbox',
        title: 'T',
        providerId: 'p1',
        modelId: 'm1',
        systemPrompt: '',
        messages: [],
        createdAt: '',
        updatedAt: '',
        agentConfig: { enabled: true },
      } as any
    })

    function seedProjects() {
      const projectsStore = useProjectsStore()
      projectsStore.projects = [
        { id: 'proj-a', path: 'D:/x/app', name: 'AppA', addedAt: '', archived: false, lastModified: null },
        { id: 'proj-b', path: 'D:/y/app', name: 'AppB', addedAt: '', archived: false, lastModified: null },
      ] as any
      projectsStore.virtualProjects = [
        {
          id: 'virtual-room1', path: 'Z:/remote', name: 'Remote', addedAt: '',
          archived: false, lastModified: null, virtual: true, roomId: 'room1',
        } as any,
      ]
      return useProjectsStore()
    }

    it('绑定合法候选 → 写 agentConfig.projectPath 并持久化', async () => {
      seedProjects()
      const ai = await import('@/services/ai')
      vi.mocked(ai.updateConversation).mockClear()
      store.sandboxProject = { id: 'proj-a', path: 'D:/x/app', name: 'AppA' } as any
      await new Promise((r) => setTimeout(r, 0))
      expect(store.currentConversation!.agentConfig!.projectPath).toBe('D:/x/app')
      expect(ai.updateConversation).toHaveBeenCalledWith(
        'conv-sandbox',
        expect.objectContaining({ agentConfig: expect.objectContaining({ projectPath: 'D:/x/app' }) })
      )
    })

    it('虚拟项目候选被拒绝（G1）', async () => {
      seedProjects()
      const before = store.currentConversation!.agentConfig!.projectPath
      store.sandboxProject = {
        id: 'virtual-room1', path: 'Z:/remote', name: 'Remote',
        virtual: true, roomId: 'room1',
      } as any
      await new Promise((r) => setTimeout(r, 0))
      expect(store.currentConversation!.agentConfig!.projectPath).toBe(before)
    })

    it('未注册/归档候选被拒绝', async () => {
      seedProjects()
      // 归档：activeProjects 已过滤（projects 含 archived 项）
      store.sandboxProject = {
        id: 'proj-a', path: 'D:/x/app', name: 'AppA', archived: true,
      } as any
      await new Promise((r) => setTimeout(r, 0))
      expect(store.currentConversation!.agentConfig!.projectPath).toBeUndefined()
      // 未注册
      store.sandboxProject = { id: 'ghost', path: 'D:/z', name: 'Ghost' } as any
      await new Promise((r) => setTimeout(r, 0))
      expect(store.currentConversation!.agentConfig!.projectPath).toBeUndefined()
    })

    it('解绑（null）→ projectPath 清空', async () => {
      seedProjects()
      store.currentConversation!.agentConfig!.projectPath = 'D:/x/app'
      store.sandboxProject = null
      await new Promise((r) => setTimeout(r, 0))
      expect(store.currentConversation!.agentConfig!.projectPath).toBe('')
    })

    it('无当前对话时先创建再绑定', async () => {
      seedProjects()
      store.currentConversation = null
      const ai = await import('@/services/ai')
      vi.mocked(ai.createConversation).mockResolvedValueOnce({
        id: 'new-conv', title: '新对话', providerId: '', modelId: '',
        systemPrompt: '', messages: [], createdAt: '', updatedAt: '',
        agentConfig: {},
      } as any)
      store.sandboxProject = { id: 'proj-a', path: 'D:/x/app', name: 'AppA' } as any
      await new Promise((r) => setTimeout(r, 0))
      expect(store.currentConversation).toBeTruthy()
      expect(store.currentConversation!.agentConfig!.projectPath).toBe('D:/x/app')
    })

    it('getter 绑定失效（路径不在 activeProjects）→ null + sandboxInvalidated', () => {
      seedProjects()
      store.currentConversation!.agentConfig!.projectPath = 'D:/gone/old'
      expect(store.sandboxProject).toBeNull()
      expect(store.sandboxInvalidated).toBe(true)
      store.ackSandboxInvalidation()
      expect(store.sandboxInvalidated).toBe(false)
    })

    it('getter 绑定有效 → 返回项目对象（排除虚拟同名路径）', () => {
      seedProjects()
      store.currentConversation!.agentConfig!.projectPath = 'D:/x/app'
      expect(store.sandboxProject?.id).toBe('proj-a')
    })
  })

  // ── S14: insertReference 统一插入 + 引用提取 ─────────────────
  describe('S14: insertReference / extractReferences', () => {
    let store: ReturnType<typeof useChatStore>

    beforeEach(() => {
      setActivePinia(createPinia())
      store = useChatStore()
    })

    it('追加模式：draft 末尾追加内部标记 @{projectId}:relpath', () => {
      store.draft = '帮我看看'
      store.insertReference('proj-1', 'src/main.py')
      expect(store.draft).toBe('帮我看看 @proj-1:src/main.py ')
    })

    it('空草稿直接插入', () => {
      store.insertReference('proj-1', 'a.py')
      expect(store.draft).toBe('@proj-1:a.py ')
    })

    it('替换未完成的 @<id>:<filter> token（第二层导航残留）', () => {
      store.draft = '请查看 @proj-1:sr'
      store.insertReference('proj-1', 'src/main.py')
      expect(store.draft).toBe('请查看 @proj-1:src/main.py ')
    })

    it('insertReference 递增 focusRequestId（触发输入框聚焦）', () => {
      store.draft = ''
      const before = store.focusRequestId
      store.insertReference('proj-1', 'a.py')
      expect(store.focusRequestId).toBe(before + 1)
    })

    it('extractReferences 从文本提取 files（content 原文保留）', async () => {
      const { extractReferences } = await import('@/utils/refs')
      const files = extractReferences('看看 @proj-1:src/main.py 和 @proj-2:readme.md')
      expect(files).toEqual([
        { projectId: 'proj-1', path: 'src/main.py' },
        { projectId: 'proj-2', path: 'readme.md' },
      ])
      // 普通邮箱/装饰器 @ 不误提取
      expect(extractReferences('user@x.com 和 @click')).toEqual([])
    })
  })
})
