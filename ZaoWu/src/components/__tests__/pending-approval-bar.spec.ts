/**
 * 阶段 C10: PendingApprovalBar（审批浮层）组件测试。
 *
 * 验证：
 * - 无 pending 不渲染 / 有 pending 渲染（工具名 + 按钮 + 倒计时）
 * - 点击批准/始终允许/拒绝 → chatStore.confirmTool 以正确参数被调用
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useChatStore } from '@/stores/chat'
import PendingApprovalBar from '@/components/PendingApprovalBar.vue'

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
  confirmToolCall: vi.fn().mockResolvedValue(undefined),
  loadProviders: vi.fn().mockResolvedValue({ ok: true, providers: [] }),
  loadConfig: vi.fn().mockResolvedValue({ ok: true, config: {} }),
  getSkills: vi.fn().mockResolvedValue({ ok: true, skills: [] }),
  fetchSkills: vi.fn().mockResolvedValue([]),
}))

function makeConv(id = 'conv-1') {
  return {
    id,
    title: 't',
    providerId: 'p',
    modelId: 'm',
    messages: [],
    agentConfig: { enabled: true },
  } as unknown as Parameters<ReturnType<typeof useChatStore>['currentConversation'] extends never ? never : never>[number]
}

describe('PendingApprovalBar（阶段 C10 审批浮层）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const settings = useSettingsStore()
    settings.background.language = 'zh-CN'
  })

  it('无 pending 时不渲染', () => {
    const wrapper = mount(PendingApprovalBar)
    expect(wrapper.find('.approval-bar').exists()).toBe(false)
  })

  it('有 pending 时渲染：工具名 + 三态按钮 + 倒计时', async () => {
    const chat = useChatStore()
    chat.pendingByMessage.set(
      'msg-1',
      new Map([['req-1', { requestId: 'req-1', name: 'run_command', arguments: { command: 'ls' } }]])
    )
    const wrapper = mount(PendingApprovalBar)
    await nextTick()
    expect(wrapper.find('.approval-bar').exists()).toBe(true)
    expect(wrapper.text()).toContain('run_command')
    expect(wrapper.find('.btn-approve').exists()).toBe(true)
    expect(wrapper.find('.btn-approve-always').exists()).toBe(true)
    expect(wrapper.find('.btn-reject').exists()).toBe(true)
    // 倒计时初始为 60s 文案
    expect(wrapper.text()).toContain('60')
  })

  it('多 pending 时显示队列序号 1/N', async () => {
    const chat = useChatStore()
    chat.pendingByMessage.set('msg-1', new Map([['req-1', { requestId: 'req-1', name: 'a', arguments: {} }]]))
    chat.pendingByMessage.set('msg-2', new Map([['req-2', { requestId: 'req-2', name: 'b', arguments: {} }]]))
    const wrapper = mount(PendingApprovalBar)
    await nextTick()
    expect(wrapper.find('.approval-queue').exists()).toBe(true)
    expect(wrapper.text()).toContain('1 / 2')
  })

  it('点击「批准」→ confirmTool(requestId, true, once)', async () => {
    const chat = useChatStore()
    chat.currentConversation = makeConv()
    chat.pendingByMessage.set(
      'msg-1',
      new Map([['req-1', { requestId: 'req-1', name: 'run_command', arguments: { command: 'ls' } }]])
    )
    const spy = vi.spyOn(chat, 'confirmTool')
    const wrapper = mount(PendingApprovalBar)
    await nextTick()
    await wrapper.find('.btn-approve').trigger('click')
    await nextTick()
    expect(spy).toHaveBeenCalledWith('req-1', true, 'once')
  })

  it('点击「始终允许」→ confirmTool(requestId, true, always)', async () => {
    const chat = useChatStore()
    chat.currentConversation = makeConv()
    chat.pendingByMessage.set(
      'msg-1',
      new Map([['req-1', { requestId: 'req-1', name: 'write_file', arguments: { path: 'a.py' } }]])
    )
    const spy = vi.spyOn(chat, 'confirmTool')
    const wrapper = mount(PendingApprovalBar)
    await nextTick()
    await wrapper.find('.btn-approve-always').trigger('click')
    await nextTick()
    expect(spy).toHaveBeenCalledWith('req-1', true, 'always')
  })

  it('点击「拒绝」→ confirmTool(requestId, false, once)', async () => {
    const chat = useChatStore()
    chat.currentConversation = makeConv()
    chat.pendingByMessage.set(
      'msg-1',
      new Map([['req-1', { requestId: 'req-1', name: 'run_command', arguments: { command: 'rm -rf /' } }]])
    )
    const spy = vi.spyOn(chat, 'confirmTool')
    const wrapper = mount(PendingApprovalBar)
    await nextTick()
    await wrapper.find('.btn-reject').trigger('click')
    await nextTick()
    expect(spy).toHaveBeenCalledWith('req-1', false, 'once')
  })

  it('输入框聚焦时快捷键豁免（不触发 confirmTool）', async () => {
    const chat = useChatStore()
    chat.currentConversation = makeConv()
    chat.pendingByMessage.set(
      'msg-1',
      new Map([['req-1', { requestId: 'req-1', name: 'run_command', arguments: {} }]])
    )
    const spy = vi.spyOn(chat, 'confirmTool')
    const wrapper = mount(PendingApprovalBar)
    await nextTick()
    // 模拟焦点在 input（打字场景），按 Enter 不应触发批准
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await nextTick()
    expect(spy).not.toHaveBeenCalled()
    document.body.removeChild(input)
  })

  it('弹窗/遮罩打开时按 Esc 不触发拒绝（FIX-2 防劫持）', async () => {
    const chat = useChatStore()
    chat.currentConversation = makeConv()
    chat.pendingByMessage.set(
      'msg-1',
      new Map([['req-1', { requestId: 'req-1', name: 'run_command', arguments: {} }]])
    )
    const spy = vi.spyOn(chat, 'confirmTool')
    mount(PendingApprovalBar)
    await nextTick()
    // 模拟弹窗遮罩存在（如设置/确认框），按 Esc 关闭弹窗不应拒绝工具
    const overlay = document.createElement('div')
    overlay.className = 'dialog-overlay'
    document.body.appendChild(overlay)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(spy).not.toHaveBeenCalled()
    document.body.removeChild(overlay)
  })

  it('事件目标为按钮时按 Enter 不触发批准（FIX-2 防劫持）', async () => {
    const chat = useChatStore()
    chat.currentConversation = makeConv()
    chat.pendingByMessage.set(
      'msg-1',
      new Map([['req-1', { requestId: 'req-1', name: 'run_command', arguments: {} }]])
    )
    const spy = vi.spyOn(chat, 'confirmTool')
    mount(PendingApprovalBar)
    await nextTick()
    // 焦点在按钮（非 input），按 Enter 激活按钮不应同时批准工具
    const btn = document.createElement('button')
    document.body.appendChild(btn)
    btn.focus()
    btn.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await nextTick()
    expect(spy).not.toHaveBeenCalled()
    document.body.removeChild(btn)
  })
})
