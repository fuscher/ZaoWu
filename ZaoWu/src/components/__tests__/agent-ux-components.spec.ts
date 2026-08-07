/**
 * 阶段 C12 — §8.3 前端组件测试：
 * - ToolCallCard denied + plan_mode_readonly → 黄色"被约束"（非错误）
 * - ErrorCard 渲染 + CTA 可点
 * - MessageBubble quality 分级渲染 + 存量空气泡回退 + 旧消息默认 success
 * - ModeBadge plan/build 两态
 * - PhaseStrip phase 链渲染
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import ToolCallCard from '@/components/ToolCallCard.vue'
import ErrorCard from '@/components/ErrorCard.vue'
import MessageBubble from '@/components/MessageBubble.vue'
import ModeBadge from '@/components/ModeBadge.vue'
import PhaseStrip from '@/components/PhaseStrip.vue'
import { useChatStore } from '@/stores/chat'

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

describe('阶段 C 组件测试', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const settings = useSettingsStore()
    settings.background.language = 'zh-CN'
  })

  describe('ToolCallCard: tool_part denied + plan_mode_readonly 渲染"被约束"', () => {
    it('denied + plan_mode_readonly → constrained 类（黄色），非 error', () => {
      const wrapper = mount(ToolCallCard, {
        props: {
          toolCall: { requestId: 'tc-1', name: 'write_file', arguments: { path: 'a.py' } },
          part: { requestId: 'tc-1', name: 'write_file', part: 'denied', reason: 'plan_mode_readonly', ts: 1 },
        },
      })
      expect(wrapper.classes()).toContain('constrained')
      expect(wrapper.classes()).not.toContain('error')
    })

    it('failed 渲染 error 类（红色）', () => {
      const wrapper = mount(ToolCallCard, {
        props: {
          toolCall: { requestId: 'tc-2', name: 'run_command', arguments: {} },
          part: { requestId: 'tc-2', name: 'run_command', part: 'failed', reason: 'execute_error', ts: 1 },
        },
      })
      expect(wrapper.classes()).toContain('error')
    })

    it('D 修复: denied 区块标题不再渲染字面量 agent.error（i18n 对象化后）', async () => {
      const wrapper = mount(ToolCallCard, {
        props: {
          toolCall: { requestId: 'tc-3', name: 'write_file', arguments: { path: 'a.py' } },
          part: { requestId: 'tc-3', name: 'write_file', part: 'denied', reason: 'plan_mode_readonly', ts: 1 },
        },
      })
      await wrapper.find('.tool-call-header').trigger('click')
      await nextTick()
      // 展开后 denied 原因区标题应为 i18n 文案而非原始 key
      expect(wrapper.text()).not.toContain('agent.error')
      expect(wrapper.text()).toContain('当前模式禁止写操作')
    })
  })

  describe('ErrorCard: 错误卡片 + CTA', () => {
    it('渲染错误码 + CTA 可点', async () => {
      const wrapper = mount(ErrorCard, {
        props: {
          error: {
            code: 'llm_auth',
            message: 'API 鉴权失败，请检查 Provider 配置',
            traceId: 'trace-abc',
            recovery: [
              { label: '前往 Provider 设置', action: 'open:settings:providers' },
              { label: '重试', action: 'retry' },
            ],
          },
        },
      })
      const buttons = wrapper.findAll('.cta-btn')
      expect(buttons.length).toBe(2)
      expect(wrapper.text()).toContain('llm_auth')
      expect(wrapper.text()).toContain('trace-abc')
      await buttons[0]!.trigger('click')
      expect(wrapper.emitted('action')?.[0]).toEqual(['open:settings:providers'])
    })
  })

  describe('MessageBubble: 完成态分级渲染', () => {
    function mountBubble(message: Record<string, unknown>, isStreaming = false) {
      return mount(MessageBubble, {
        props: {
          message: message as any,
          isStreaming,
        },
        global: {
          stubs: {
            PhaseStrip: true,
            ToolCallCard: true,
            ErrorCard: true,
          },
        },
      })
    }

    it('quality=idle → 气泡带 quality-idle 类 + 重试 CTA', () => {
      const wrapper = mountBubble({
        id: 'm1',
        role: 'assistant',
        content: '我先读取文件看看',
        timestamp: 1,
        metadata: { quality: 'idle' },
      })
      expect(wrapper.classes()).toContain('quality-idle')
      expect(wrapper.find('.quality-cta').text()).toBe('重试')
    })

    it('quality=constrained → 切执行模式 CTA', () => {
      const wrapper = mountBubble({
        id: 'm2',
        role: 'assistant',
        content: '## 重构方案',
        timestamp: 1,
        metadata: { quality: 'constrained' },
      })
      expect(wrapper.classes()).toContain('quality-constrained')
      expect(wrapper.text()).toContain('切换到执行模式并继续')
    })

    it('存量空气泡回退: (completed) 无 metadata → empty 渲染', () => {
      const wrapper = mountBubble({
        id: 'm3',
        role: 'assistant',
        content: '(completed)',
        timestamp: 1,
      })
      expect(wrapper.classes()).toContain('quality-empty')
    })

    it('存量错误回退: [请求失败: …] → error_fallback 挂 ErrorCard', () => {
      const wrapper = mountBubble({
        id: 'm4',
        role: 'assistant',
        content: '[请求失败: 超时]',
        timestamp: 1,
      })
      expect(wrapper.classes()).toContain('quality-error_fallback')
    })

    it('旧消息无 quality → success（无分级类）', () => {
      const wrapper = mountBubble({
        id: 'm5',
        role: 'assistant',
        content: '正常结论',
        timestamp: 1,
      })
      expect(wrapper.classes()).not.toContain('quality-idle')
      expect(wrapper.classes()).not.toContain('quality-empty')
      expect(wrapper.classes()).not.toContain('quality-constrained')
    })

    it('D 修复: error_recovery 从 metadata 恢复 → ErrorCard 渲染 CTA（终态错误恢复）', () => {
      // 不 stub ErrorCard，验证 recovery 从 metadata 传到卡片并渲染 CTA
      const wrapper = mount(MessageBubble, {
        props: {
          message: {
            id: 'm6',
            role: 'assistant',
            content: '',
            timestamp: 1,
            metadata: {
              quality: 'error_fallback',
              error_code: 'llm_auth',
              error_message: 'API 鉴权失败',
              error_recovery: [{ label: '重试', action: 'retry' }],
            },
          },
          isStreaming: false,
        },
        global: { stubs: { PhaseStrip: true, ToolCallCard: true } },
      })
      expect(wrapper.find('.error-card').exists()).toBe(true)
      expect(wrapper.find('.cta-btn').text()).toBe('重试')
    })

    it('D 修复: MessageBubble 根元素带 msg- 锚点（scroll_to_plan 可定位）', () => {
      const wrapper = mountBubble({ id: 'm7', role: 'assistant', content: 'ok', timestamp: 1 })
      expect(wrapper.attributes('id')).toBe('msg-m7')
    })

    it('点击重试 CTA → 重发最近 user message', async () => {
      const chat = useChatStore()
      chat.currentConversation = {
        id: 'conv-x',
        title: 'T',
        providerId: 'p1',
        modelId: 'm1',
        systemPrompt: '',
        messages: [],
        createdAt: '',
        updatedAt: '',
        agentConfig: { enabled: true },
      } as any
      const { sendAgentMessageStream } = await import('@/services/ai')
      vi.mocked(sendAgentMessageStream).mockImplementation(
        async () => new AbortController()
      )
      chat.currentConversation!.messages.push({
        id: 'u1',
        role: 'user',
        content: '为什么失败了',
        timestamp: 1,
      } as any)

      const wrapper = mountBubble({
        id: 'a1',
        role: 'assistant',
        content: '我先读取',
        timestamp: 2,
        metadata: { quality: 'idle' },
      })
      await wrapper.find('.quality-cta').trigger('click')
      await nextTick()
      const calls = vi.mocked(sendAgentMessageStream).mock.calls
      expect(calls[calls.length - 1]?.[1]).toBe('为什么失败了')
    })
  })

  describe('ModeBadge: plan/build 两态', () => {
    it('plan 渲染计划徽章', () => {
      const wrapper = mount(ModeBadge, { props: { preset: 'plan' } })
      expect(wrapper.classes()).toContain('plan')
      expect(wrapper.text()).toContain('计划模式')
    })

    it('build 渲染执行徽章', () => {
      const wrapper = mount(ModeBadge, { props: { preset: 'build' } })
      expect(wrapper.classes()).toContain('build')
      expect(wrapper.text()).toContain('执行模式')
    })
  })

  describe('PhaseStrip: phase 链渲染 + notice 子节点', () => {
    it('渲染思考/工具链 + notice 子节点', async () => {
      const wrapper = mount(PhaseStrip, {
        props: {
          phases: [
            { phase: 'thinking', ts: 1 },
            {
              phase: 'tool',
              ts: 2,
              notices: [{ level: 'info', code: 'compacted', message: '已压缩', ts: 2 }],
            },
          ],
        },
      })
      // 折叠态默认显示当前节点；展开后可见全部
      await wrapper.find('.phase-toggle').trigger('click')
      await nextTick()
      expect(wrapper.text()).toContain('思考中')
      expect(wrapper.text()).toContain('工具调用')
      expect(wrapper.text()).toContain('已压缩')
    })
  })
})
