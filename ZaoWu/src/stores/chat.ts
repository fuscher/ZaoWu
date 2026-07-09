import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { Conversation, Message, LLMProvider, LLMConfig } from '@/types'
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
      return conv
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

  function stopStreaming() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    if (streamingMessageId.value) {
      ai.stopGeneration(streamingMessageId.value)
    }
    isStreaming.value = false
    streamingMessageId.value = null
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
  }
})
