import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { Conversation, Message, LLMProvider, LLMConfig, ToolCall, ToolResult, Skill } from '@/types'
import * as ai from '@/services/ai'

export const useChatStore = defineStore('chat', () => {
  // ── State ──────────────────────────────────────────────
  const conversations = ref<Conversation[]>([])
  const currentConversation = ref<Conversation | null>(null)
  const providers = ref<LLMProvider[]>([])
  const config = ref<LLMConfig>({
    defaultProviderId: '',
    defaultModelId: '',
    temperature: 0.7,
    maxTokens: 4096,
    topP: 1.0,
    systemPrompt: 'You are a helpful assistant.',
  })
  const isLoading = ref(false)
  const isStreaming = ref(false)
  const streamingMessageId = ref<string | null>(null)
  const error = ref('')
  let abortController: AbortController | null = null

  // ── Agent state (Stage 8) ────────────────────────────────
  // agentMode 与当前对话的 agentConfig.enabled 绑定，切换时自动持久化。
  const agentMode = computed<boolean>({
    get: () => currentConversation.value?.agentConfig?.enabled ?? false,
    set: async (value) => {
      const conv = currentConversation.value
      if (!conv) return
      const nextConfig = { ...(conv.agentConfig || {}), enabled: value }
      conv.agentConfig = nextConfig
      try {
        await ai.updateConversation(conv.id, { agentConfig: nextConfig })
      } catch {
        // 失败时回退本地状态
        conv.agentConfig = { ...conv.agentConfig, enabled: !value }
      }
    },
  })
  // F02: 工具调用状态按 messageId 两级索引 — Key: messageId → Map<requestId, ToolCall | ToolResult>
  // 修复历史气泡显示当前工具结果的问题：每条 assistant 消息只持有自己那轮的工具调用。
  const toolCallsByMessage = ref<Map<string, Map<string, ToolCall>>>(new Map())
  const toolResultsByMessage = ref<Map<string, Map<string, ToolResult>>>(new Map())
  const pendingByMessage = ref<Map<string, Map<string, ToolCall>>>(new Map())

  // ── Skill state ─────────────────────────────────────────
  const availableSkills = ref<Skill[]>([])
  const selectedSkill = computed<string | undefined>({
    get: () => currentConversation.value?.agentConfig?.selectedSkill,
    set: async (value) => {
      const conv = currentConversation.value
      if (!conv) return
      // Normalize an empty string ("no skill" option) to undefined.
      const normalized = value || undefined
      const nextConfig = { ...(conv.agentConfig || {}), selectedSkill: normalized }
      conv.agentConfig = nextConfig
      try {
        await ai.updateConversation(conv.id, { agentConfig: nextConfig })
      } catch {
        conv.agentConfig = { ...conv.agentConfig, selectedSkill: undefined }
      }
    },
  })

  // F04: 自动批准写入文件 — 仅影响 write_file，run_command 仍需手动确认。
  // 与 agentMode/selectedSkill 一样绑定到当前对话的 agentConfig，切换时自动持久化。
  const autoApproveWrites = computed<boolean>({
    get: () => currentConversation.value?.agentConfig?.autoApproveWrites ?? false,
    set: async (value) => {
      const conv = currentConversation.value
      if (!conv) return
      const nextConfig = { ...(conv.agentConfig || {}), autoApproveWrites: value }
      conv.agentConfig = nextConfig
      try {
        await ai.updateConversation(conv.id, { agentConfig: nextConfig })
      } catch {
        // 失败时回退本地状态
        conv.agentConfig = { ...conv.agentConfig, autoApproveWrites: !value }
      }
    },
  })

  // ── Computed ───────────────────────────────────────────
  const currentMessages = computed(() => currentConversation.value?.messages || [])
  const currentProvider = computed(() =>
    providers.value.find((p) => p.id === currentConversation.value?.providerId)
  )
  const currentModels = computed(() => currentProvider.value?.models || [])
  const hasProvider = computed(() => providers.value.length > 0)

  // ── Provider & Config ─────────────────────────────────
  async function loadProviders() {
    try {
      providers.value = await ai.fetchProviders()
    } catch {
      // silent
    }
  }

  async function loadConfig() {
    try {
      const c = await ai.fetchConfig()
      config.value = c
    } catch {
      // silent
    }
  }

  async function updateConfig(partial: Partial<LLMConfig>) {
    try {
      const c = await ai.saveConfig(partial)
      config.value = c
    } catch {
      // silent
    }
  }

  async function loadSkills() {
    try {
      availableSkills.value = await ai.fetchSkills()
    } catch {
      // silent
    }
  }

  async function enableSkill(name: string) {
    await ai.enableSkill(name)
    const skill = availableSkills.value.find((s) => s.name === name)
    if (skill) skill.enabled = true
  }

  async function disableSkill(name: string) {
    await ai.disableSkill(name)
    const skill = availableSkills.value.find((s) => s.name === name)
    if (skill) skill.enabled = false
    // 如果当前对话正使用该 skill，清空选择
    if (selectedSkill.value === name) {
      selectedSkill.value = undefined
    }
  }

  async function deleteSkill(name: string) {
    await ai.deleteSkill(name)
    availableSkills.value = availableSkills.value.filter((s) => s.name !== name)
    if (selectedSkill.value === name) {
      selectedSkill.value = undefined
    }
  }

  async function importSkill(content: string): Promise<Skill> {
    const skill = await ai.importSkill(content)
    const idx = availableSkills.value.findIndex((s) => s.name === skill.name)
    if (idx !== -1) {
      availableSkills.value[idx] = skill
    } else {
      availableSkills.value.push(skill)
    }
    return skill
  }

  async function refreshModels(providerId: string) {
    try {
      const models = await ai.fetchModels(providerId)
      const provider = providers.value.find((p) => p.id === providerId)
      if (provider) {
        provider.models = models as LLMProvider['models']
      }
    } catch {
      // silent
    }
  }

  // ── Conversations ─────────────────────────────────────
  async function loadConversations() {
    try {
      conversations.value = await ai.fetchConversations()
      if (currentConversation.value) {
        const updated = conversations.value.find((c) => c.id === currentConversation.value!.id)
        if (updated) {
          currentConversation.value.title = updated.title
          currentConversation.value.messageCount = updated.messageCount
        }
      }
    } catch {
      // silent
    }
  }

  async function createNewConversation(params?: {
    title?: string
    providerId?: string
    modelId?: string
    systemPrompt?: string
  }): Promise<Conversation | null> {
    try {
      const conv = await ai.createConversation({
        title: params?.title || '新对话',
        providerId: params?.providerId || config.value.defaultProviderId,
        modelId: params?.modelId || config.value.defaultModelId,
        systemPrompt: params?.systemPrompt,
      })
      conversations.value.unshift(conv)
      currentConversation.value = conv
      return currentConversation.value
    } catch {
      return null
    }
  }

  async function switchConversation(id: string) {
    if (currentConversation.value?.id === id) return
    isLoading.value = true
    try {
      const conv = await ai.getConversation(id)
      currentConversation.value = conv
    } catch {
      error.value = '加载对话失败'
    } finally {
      isLoading.value = false
    }
    // F02: 切换对话时清空工具调用 Map，避免长期会话内存无限增长。
    // message.id 不携带 convId 前缀，故直接 clear() 全部 Map（当前工具卡片只渲染当前对话消息，清空无影响）。
    clearToolMaps()
  }

  async function renameConversation(id: string, title: string) {
    try {
      const conv = await ai.updateConversation(id, { title })
      const idx = conversations.value.findIndex((c) => c.id === id)
      if (idx !== -1 && conversations.value[idx]) conversations.value[idx].title = title
      if (currentConversation.value?.id === id) {
        currentConversation.value.title = title
      }
    } catch {
      // silent
    }
  }

  async function removeConversation(id: string) {
    try {
      await ai.deleteConversation(id)
      conversations.value = conversations.value.filter((c) => c.id !== id)
      if (currentConversation.value?.id === id) {
        currentConversation.value = null
      }
    } catch {
      // silent
    }
  }

  async function clearMessages() {
    if (!currentConversation.value) return
    try {
      await ai.clearConversation(currentConversation.value.id)
      currentConversation.value.messages = []
    } catch {
      // silent
    }
  }

  // ── Message Sending ───────────────────────────────────
  async function sendMessage(
    content: string,
    params?: { temperature?: number; maxTokens?: number; topP?: number }
  ) {
    if (!content.trim() || isStreaming.value) return

    let conv = currentConversation.value
    if (!conv) {
      conv = await createNewConversation()
      if (!conv) return
    }

    const userMessage: Message = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content,
      timestamp: Date.now(),
    }
    conv.messages.push(userMessage)

    isStreaming.value = true
    error.value = ''

    const assistantMessage: Message = {
      id: `stream-${Date.now()}`,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      model: conv.modelId,
    }
    conv.messages.push(assistantMessage)
    streamingMessageId.value = assistantMessage.id

    abortController = await ai.sendMessageStream(
      conv.id,
      content,
      {
        onDelta(_messageId: string, delta: string) {
          assistantMessage.content += delta
        },
        onDone(messageId: string, fullContent: string) {
          assistantMessage.content = fullContent
          assistantMessage.id = messageId
          isStreaming.value = false
          streamingMessageId.value = null
        },
        onError(err: string) {
          assistantMessage.content += `\n\n⚠️ ${err}`
          isStreaming.value = false
          streamingMessageId.value = null
          error.value = err
        },
      },
      params
    )

    loadConversations()
  }

  async function confirmTool(requestId: string, approved: boolean) {
    const conv = currentConversation.value
    if (!conv) return
    try {
      await ai.confirmToolCall(conv.id, requestId, approved)
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'confirm failed'
    }
  }

  // F02: 按 messageId 读取工具调用状态的 accessor，供 MessageBubble 使用。
  function toolCallsFor(messageId: string): Map<string, ToolCall> {
    return toolCallsByMessage.value.get(messageId) || new Map()
  }
  function toolResultsFor(messageId: string): Map<string, ToolResult> {
    return toolResultsByMessage.value.get(messageId) || new Map()
  }
  function pendingFor(messageId: string): Map<string, ToolCall> {
    return pendingByMessage.value.get(messageId) || new Map()
  }
  // F02: 清空全部工具调用 Map（切换对话 / 停止生成时调用）。
  function clearToolMaps() {
    toolCallsByMessage.value.clear()
    toolResultsByMessage.value.clear()
    pendingByMessage.value.clear()
  }

  function stopStreaming() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    if (agentMode.value && currentConversation.value) {
      ai.stopAgentGeneration(currentConversation.value.id)
    } else if (streamingMessageId.value) {
      ai.stopGeneration(streamingMessageId.value)
    }
    isStreaming.value = false
    streamingMessageId.value = null
    clearToolMaps()
  }

  // ── Agent message sending (Stage 8) ──────────────────────
  async function sendAgentMessage(
    content: string,
    params?: { temperature?: number; maxTokens?: number; topP?: number }
  ) {
    if (!content.trim() || isStreaming.value) return

    let conv = currentConversation.value
    if (!conv) {
      conv = await createNewConversation()
      if (!conv) return
    }

    const userMessage: Message = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content,
      timestamp: Date.now(),
    }
    conv.messages.push(userMessage)

    isStreaming.value = true
    error.value = ''

    const assistantMessage: Message = {
      id: `stream-${Date.now()}`,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      model: conv.modelId,
    }
    conv.messages.push(assistantMessage)
    streamingMessageId.value = assistantMessage.id

    // F02: 为当前 assistant 消息创建独立的工具调用存储槽（按 messageId 索引），
    // 不再清空全局 Map，避免新消息清空历史气泡的工具卡片。
    const mid = assistantMessage.id
    toolCallsByMessage.value.set(mid, new Map())
    toolResultsByMessage.value.set(mid, new Map())
    pendingByMessage.value.set(mid, new Map())

    abortController = await ai.sendAgentMessageStream(
      conv.id,
      content,
      {
        onDelta(_messageId: string, delta: string) {
          assistantMessage.content += delta
        },
        onToolCallStart(_messageId: string, toolCall: ToolCall) {
          toolCallsByMessage.value.get(mid)?.set(toolCall.requestId, toolCall)
        },
        onRequiresConfirmation(_messageId: string, toolCall: ToolCall) {
          pendingByMessage.value.get(mid)?.set(toolCall.requestId, toolCall)
        },
        onToolCallEnd(_messageId: string, result: ToolResult) {
          toolResultsByMessage.value.get(mid)?.set(result.requestId, result)
          pendingByMessage.value.get(mid)?.delete(result.requestId)
        },
        onDone(messageId: string, fullContent: string) {
          assistantMessage.content = fullContent
          assistantMessage.id = messageId
          // F02: 将工具调用数据关联到最终的持久化 messageId（流式临时 id 与持久化 id 不同）
          if (messageId !== mid) {
            const calls = toolCallsByMessage.value.get(mid)
            const results = toolResultsByMessage.value.get(mid)
            const pending = pendingByMessage.value.get(mid)
            if (calls) toolCallsByMessage.value.set(messageId, calls)
            if (results) toolResultsByMessage.value.set(messageId, results)
            if (pending) pendingByMessage.value.set(messageId, pending)
            toolCallsByMessage.value.delete(mid)
            toolResultsByMessage.value.delete(mid)
            pendingByMessage.value.delete(mid)
          }
          isStreaming.value = false
          streamingMessageId.value = null
        },
        onError(err: string) {
          assistantMessage.content += `\n\n⚠️ ${err}`
          isStreaming.value = false
          streamingMessageId.value = null
          error.value = err
        },
      },
      params
    )

    loadConversations()
  }

  // ── Init ──────────────────────────────────────────────
  async function init() {
    await Promise.all([loadProviders(), loadConfig(), loadConversations()])
  }

  return {
    conversations,
    currentConversation,
    providers,
    config,
    isLoading,
    isStreaming,
    streamingMessageId,
    error,
    currentMessages,
    currentProvider,
    currentModels,
    hasProvider,
    loadProviders,
    loadConfig,
    updateConfig,
    refreshModels,
    loadConversations,
    createNewConversation,
    switchConversation,
    renameConversation,
    removeConversation,
    clearMessages,
    sendMessage,
    stopStreaming,
    init,
    // Agent mode
    agentMode,
    autoApproveWrites,
    toolCallsByMessage,
    toolResultsByMessage,
    pendingByMessage,
    toolCallsFor,
    toolResultsFor,
    pendingFor,
    clearToolMaps,
    sendAgentMessage,
    confirmTool,
    // Skills
    availableSkills,
    selectedSkill,
    loadSkills,
    enableSkill,
    disableSkill,
    deleteSkill,
    importSkill,
  }
})
