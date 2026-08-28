/**
 * 阶段 C12 — §8.3 前端组件测试：
 * - ToolCallCard denied + plan_mode_readonly → 黄色"被约束"（非错误）
 * - ErrorCard 渲染 + CTA 可点
 * - MessageBubble quality 分级渲染 + 存量空气泡回退 + 旧消息默认 success
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
import PhaseStrip from '@/components/PhaseStrip.vue'
import ChatInput from '@/components/ChatInput.vue'
import FileTreeNode from '@/components/FileTreeNode.vue'
import { useChatStore } from '@/stores/chat'
import { useProjectsStore } from '@/stores/projects'

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
  fetchSkills: vi.fn().mockResolvedValue([]),
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

  describe('PhaseStrip: phase 链渲染 + notice 子节点', () => {
    it('渲染思考/工具链 + notice 子节点（i18n 文案优先）', async () => {
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
      // notice 文案走 i18n 键（agent.notice.compacted），非后端原始 message
      expect(wrapper.text()).toContain('上下文较长，已自动压缩早期对话')
      expect(wrapper.text()).not.toContain('已压缩')
    })
  })
})

// ── S13-P0-3: Anthropic 供应商禁用 Agent 开关 ──────────────────

const _chatInputStubs = {
  ModelSwitcher: true,
  ParameterPanel: true,
  ErrorToast: true,
  // lucide 图标在测试环境无全局注册，stub 为占位
  Send: true,
  Square: true,
  Bot: true,
  Sparkles: true,
  Hammer: true,
  ClipboardList: true,
}

function _mountChatInput() {
  return mount(ChatInput, { global: { stubs: _chatInputStubs } })
}

describe('S13-P0-3: Agent 开关 Anthropic 禁用态', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const settings = useSettingsStore()
    settings.background.language = 'zh-CN'
  })

  function setupProvider(protocol: string, convId: string) {
    const chat = useChatStore()
    chat.providers = [
      {
        id: `${protocol}-1`,
        name: protocol,
        protocol,
        apiBase: `https://api.${protocol}.com`,
        models: [{ id: `${protocol}-m1` }],
      } as any,
    ]
    chat.currentConversation = {
      id: convId,
      title: 'T',
      providerId: `${protocol}-1`,
      modelId: `${protocol}-m1`,
      systemPrompt: '',
      messages: [],
      createdAt: '',
      updatedAt: '',
      agentConfig: { enabled: false },
    } as any
  }

  it('Anthropic 供应商 → 开关 disabled + title 提示', async () => {
    setupProvider('anthropic', 'conv-anth')
    const wrapper = _mountChatInput()
    await nextTick()
    const btn = wrapper.find('.agent-toggle')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.attributes('title')).toContain('Anthropic')
  })

  it('Anthropic 供应商 → 点击不切换 agentMode', async () => {
    setupProvider('anthropic', 'conv-anth-2')
    const wrapper = _mountChatInput()
    await nextTick()
    const chat = useChatStore()
    expect(chat.agentMode).toBe(false)
    await wrapper.find('.agent-toggle').trigger('click')
    expect(chat.agentMode).toBe(false)
  })

  it('OpenAI 兼容供应商 → 开关可点且切换成功', async () => {
    setupProvider('openai', 'conv-oa')
    const wrapper = _mountChatInput()
    await nextTick()
    const btn = wrapper.find('.agent-toggle')
    expect(btn.attributes('disabled')).toBeUndefined()
    const chat = useChatStore()
    await btn.trigger('click')
    expect(chat.agentMode).toBe(true)
  })
})

// ── S14-P1-1/P1-2: @ 引用浮层触发与门控 ───────────────────────

const _mentionStubs = {
  ..._chatInputStubs,
  ProjectIndicator: true,
}

function _mountChatInputForMention() {
  return mount(ChatInput, { global: { stubs: _mentionStubs } })
}

/** 输入 @ 并把光标置于其后（模拟真实键入位置） */
async function _typeAt(wrapper: ReturnType<typeof mount>, text: string, caret?: number) {
  const ta = wrapper.find('textarea')
  await ta.setValue(text)
  const pos = caret ?? text.length
  ;(ta.element as HTMLTextAreaElement).setSelectionRange(pos, pos)
  await ta.trigger('input')
  await nextTick()
}

describe('S14: @ 引用浮层触发与键盘门控', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    const settings = useSettingsStore()
    settings.background.language = 'zh-CN'
    // get-tree 请求兜底（选中项目进入第二层时触发）
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, tree: [] }) })
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function setup(agentEnabled: boolean) {
    const chat = useChatStore()
    chat.currentConversation = {
      id: 'conv-mention',
      title: 'T',
      providerId: 'p1',
      modelId: 'm1',
      systemPrompt: '',
      messages: [],
      createdAt: '',
      updatedAt: '',
      agentConfig: { enabled: agentEnabled },
    } as any
    const projectsStore = useProjectsStore()
    projectsStore.projects = [
      { id: 'proj-1', path: 'D:/x/app', name: 'AppA', addedAt: '', archived: false, lastModified: null },
      { id: 'proj-2', path: 'D:/y/lib', name: 'LibB', addedAt: '', archived: false, lastModified: null },
    ] as any
    projectsStore.virtualProjects = [
      {
        id: 'virtual-room1', path: 'Z:/remote', name: 'RemoteRoom', addedAt: '',
        archived: false, lastModified: null, virtual: true, roomId: 'room1',
      } as any,
    ]
  }

  it('agent 模式输入 @ → 弹第一层且过滤虚拟项目（G1/G4）', async () => {
    setup(true)
    const wrapper = _mountChatInputForMention()
    await _typeAt(wrapper, '@')
    expect(wrapper.find('.mention-popup').exists()).toBe(true)
    expect(wrapper.text()).toContain('AppA')
    expect(wrapper.text()).toContain('LibB')
    expect(wrapper.text()).not.toContain('RemoteRoom')
  })

  it('非 agent 模式输入 @ → 不弹（G4）', async () => {
    setup(false)
    const wrapper = _mountChatInputForMention()
    await _typeAt(wrapper, '@')
    expect(wrapper.find('.mention-popup').exists()).toBe(false)
  })

  it('邮箱/装饰器不弹；全角标点前可弹（3.3）', async () => {
    setup(true)
    const wrapper = _mountChatInputForMention()
    await _typeAt(wrapper, 'user@x.com', 9)
    expect(wrapper.find('.mention-popup').exists()).toBe(false)
    await _typeAt(wrapper, 'const a = @click', 14)
    expect(wrapper.find('.mention-popup').exists()).toBe(false)
    // 全角标点后输入 @ → 触发
    await _typeAt(wrapper, '检查一下：@', 6)
    expect(wrapper.find('.mention-popup').exists()).toBe(true)
  })

  it('首次触发显示引导行（localStorage 标记），关闭后再次触发不再显示', async () => {
    setup(true)
    const wrapper = _mountChatInputForMention()
    await _typeAt(wrapper, '@')
    expect(wrapper.find('.hint-line').exists()).toBe(true)
    expect(localStorage.getItem('zaowu.mention.hintSeen')).toBe('1')
    // 关闭后再次触发 → 不再显示
    await wrapper.find('textarea').trigger('keydown', { key: 'Escape' })
    await nextTick()
    await _typeAt(wrapper, '请 @', 3)
    expect(wrapper.find('.mention-popup').exists()).toBe(true)
    expect(wrapper.find('.hint-line').exists()).toBe(false)
  })

  it('G3: 浮层打开时 Enter 不误发消息，而是选中项目进入第二层', async () => {
    setup(true)
    const ai = await import('@/services/ai')
    vi.mocked(ai.sendAgentMessageStream).mockClear()
    const wrapper = _mountChatInputForMention()
    await _typeAt(wrapper, '@')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    await nextTick()
    expect(vi.mocked(ai.sendAgentMessageStream)).not.toHaveBeenCalled()
    // 进入第二层（@proj-1: 前缀 + 项目文件树容器）
    expect(wrapper.find('.level2-header').exists()).toBe(true)
    const chat = useChatStore()
    expect(chat.draft).toContain('@proj-1:')
  })

  it('↑↓ 键盘导航 + Enter 选中第二个项目', async () => {
    setup(true)
    const wrapper = _mountChatInputForMention()
    await _typeAt(wrapper, '@')
    await wrapper.find('textarea').trigger('keydown', { key: 'ArrowDown' })
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    await nextTick()
    const chat = useChatStore()
    expect(chat.draft).toContain('@proj-2:')
  })

  it('ESC 关闭浮层', async () => {
    setup(true)
    const wrapper = _mountChatInputForMention()
    await _typeAt(wrapper, '@')
    await wrapper.find('textarea').trigger('keydown', { key: 'Escape' })
    await nextTick()
    expect(wrapper.find('.mention-popup').exists()).toBe(false)
  })

  it('无项目时显示引导文案', async () => {
    setup(true)
    const projectsStore = useProjectsStore()
    projectsStore.projects = []
    projectsStore.virtualProjects = []
    const wrapper = _mountChatInputForMention()
    await _typeAt(wrapper, '@')
    expect(wrapper.text()).toContain('去资源管理器添加')
  })

  it('P1-2: 第二层目录逐层懒加载展开（G6）', async () => {
    setup(true)
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init?.body))
      if (body.path === 'D:/x/app') {
        return {
          ok: true,
          json: async () => ({ ok: true, tree: [{ name: 'src', path: 'D:/x/app/src', type: 'directory' }] }),
        }
      }
      if (body.path === 'D:/x/app/src') {
        return {
          ok: true,
          json: async () => ({ ok: true, tree: [{ name: 'main.py', path: 'D:/x/app/src/main.py', type: 'file' }] }),
        }
      }
      return { ok: true, json: async () => ({ ok: true, tree: [] }) }
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = _mountChatInputForMention()
    await _typeAt(wrapper, '@')
    // 选中 proj-1 → 第二层（depth=1 顶层树）
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    await new Promise((r) => setTimeout(r, 0))
    expect(wrapper.find('.level2-header').exists()).toBe(true)
    expect(wrapper.text()).toContain('src')
    // 高亮 src（目录）→ Enter 懒加载子层
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    await new Promise((r) => setTimeout(r, 0))
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/get-tree'),
      expect.objectContaining({ body: expect.stringContaining('D:/x/app/src') })
    )
    expect(wrapper.text()).toContain('main.py')
  })

  it('P1-2: 选中文件插入内部标记 @{projectId}:relpath（完整 uuid）', async () => {
    setup(true)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          ok: true,
          tree: [{ name: 'main.py', path: 'D:/x/app/main.py', type: 'file' }],
        }),
      })
    )
    const wrapper = _mountChatInputForMention()
    await _typeAt(wrapper, '@')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' }) // 进入第二层
    await new Promise((r) => setTimeout(r, 0))
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' }) // 选中 main.py
    await new Promise((r) => setTimeout(r, 0))
    const chat = useChatStore()
    expect(chat.draft).toContain('@proj-1:main.py')
    // 浮层关闭
    expect(wrapper.find('.mention-popup').exists()).toBe(false)
  })

  it('P0-1 联动: 绑定有效 → @ 跳过项目层直接第二层（3.2 单项目状态）', async () => {
    setup(true)
    const chat = useChatStore()
    chat.currentConversation!.agentConfig!.projectPath = 'D:/x/app'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          ok: true,
          tree: [{ name: 'main.py', path: 'D:/x/app/main.py', type: 'file' }],
        }),
      })
    )
    const wrapper = _mountChatInputForMention()
    const ta = wrapper.find('textarea')
    // 直接操作元素：避免 setValue 的中间 input 事件干扰（打开即替换 @ token）
    const el = ta.element as HTMLTextAreaElement
    el.value = '@'
    el.setSelectionRange(1, 1)
    await ta.trigger('input')
    await new Promise((r) => setTimeout(r, 0))
    expect(wrapper.find('.level2-header').exists()).toBe(true)
    expect(wrapper.text()).toContain('main.py')
    expect(chat.draft).toContain('@proj-1:')
  })
})

// ── S14-P2-1: 引用 chip 渲染（MessageBubble）────────────────────

describe('S14-P2-1: 引用 chip 渲染', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const settings = useSettingsStore()
    settings.background.language = 'zh-CN'
  })

  function mountBubble(message: Record<string, unknown>) {
    return mount(MessageBubble, {
      props: { message: message as any },
      global: { stubs: { PhaseStrip: true, ToolCallCard: true, ErrorCard: true } },
    })
  }

  function seedProject(overrides: Record<string, unknown>) {
    const ps = useProjectsStore()
    ps.projects = [
      { id: 'proj-1', path: 'D:/x/app', name: 'AppA', addedAt: '', archived: false, lastModified: null, ...overrides } as any,
    ]
    return ps
  }

  it('用户消息中的引用标记渲染为 chip（@/name/relpath）', () => {
    seedProject({})
    const wrapper = mountBubble({ id: 'm1', role: 'user', content: '看看 @proj-1:src/main.py 这个文件', timestamp: 1 })
    const chip = wrapper.find('.ref-chip')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('@/AppA/src/main.py')
    expect(wrapper.text()).toContain('看看')
  })

  it('普通文本中的 @（邮箱/装饰器）不受影响', () => {
    const wrapper = mountBubble({ id: 'm2', role: 'user', content: '发邮件到 user@x.com 或 @click', timestamp: 1 })
    expect(wrapper.find('.ref-chip').exists()).toBe(false)
    expect(wrapper.text()).toContain('user@x.com')
  })

  it('点击 chip 整段移除该引用标记（不破坏正文）', async () => {
    seedProject({})
    const msg = { id: 'm3', role: 'user', content: '看看 @proj-1:src/main.py 这个文件', timestamp: 1 }
    const wrapper = mountBubble(msg)
    await wrapper.find('.ref-chip').trigger('click')
    expect(msg.content).not.toContain('@proj-1:')
    expect(msg.content).toContain('看看')
  })

  it('G8: 归档项目 chip 标注「项目已归档」', () => {
    seedProject({ archived: true })
    const wrapper = mountBubble({ id: 'm4', role: 'user', content: '@proj-1:a.py', timestamp: 1 })
    const chip = wrapper.find('.ref-chip')
    expect(chip.classes()).toContain('archived')
    expect(chip.text()).toContain('该项目已归档')
  })
})

// ── S14-P2-2: FileTree「引用到对话」────────────────────────────

describe('S14-P2-2: FileTree 引用到对话', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const settings = useSettingsStore()
    settings.background.language = 'zh-CN'
  })

  function mountNode(node: Record<string, unknown>, project: Record<string, unknown>) {
    return mount(FileTreeNode, {
      props: { node: node as any, level: 0, project: project as any },
    })
  }

  it('agent 模式文件节点 → 点击按钮调用 insertReference（内部格式一致）', async () => {
    const ps = useProjectsStore()
    const project = { id: 'proj-1', path: 'D:/x/app', name: 'AppA', addedAt: '', archived: false, lastModified: null }
    ps.projects = [project] as any
    const chat = useChatStore()
    chat.currentConversation = { id: 'c1', agentConfig: { enabled: true } } as any
    const wrapper = mountNode(
      { name: 'main.py', path: 'D:/x/app/src/main.py', type: 'file' },
      project
    )
    await wrapper.find('.ref-btn').trigger('click')
    expect(chat.draft).toContain('@proj-1:src/main.py')
  })

  it('G4: 非 agent 模式 → 按钮禁用且不插入', async () => {
    const ps = useProjectsStore()
    const project = { id: 'proj-1', path: 'D:/x/app', name: 'AppA', addedAt: '', archived: false, lastModified: null }
    ps.projects = [project] as any
    const chat = useChatStore()
    chat.currentConversation = { id: 'c2', agentConfig: { enabled: false } } as any
    const wrapper = mountNode(
      { name: 'main.py', path: 'D:/x/app/src/main.py', type: 'file' },
      project
    )
    expect(wrapper.find('.ref-btn').classes()).toContain('disabled')
    await wrapper.find('.ref-btn').trigger('click')
    expect(chat.draft).toBe('')
  })

  it('G1: 虚拟项目节点无引用按钮', () => {
    const vp = {
      id: 'virtual-room1', path: 'Z:/remote', name: 'R', addedAt: '',
      archived: false, lastModified: null, virtual: true, roomId: 'r1',
    }
    const ps = useProjectsStore()
    ps.virtualProjects = [vp] as any
    const wrapper = mountNode({ name: 'a.py', path: 'Z:/remote/a.py', type: 'file' }, vp)
    expect(wrapper.find('.ref-btn').exists()).toBe(false)
  })
})
