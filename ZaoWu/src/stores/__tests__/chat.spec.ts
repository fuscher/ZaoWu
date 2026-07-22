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
  stopGeneration: vi.fn(),
  stopAgentGeneration: vi.fn(),
  loadProviders: vi.fn().mockResolvedValue({ ok: true, providers: [] }),
  loadConfig: vi.fn().mockResolvedValue({ ok: true, config: {} }),
  getSkills: vi.fn().mockResolvedValue({ ok: true, skills: [] }),
}))

import { useChatStore } from '@/stores/chat'
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
})
