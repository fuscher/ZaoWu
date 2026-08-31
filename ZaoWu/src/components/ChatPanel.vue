<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { MessageSquarePlus } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'
import type { ToolCall, ToolResult } from '@/types'
import ChatToolbar from './ChatToolbar.vue'
import ChatInput from './ChatInput.vue'
import MessageBubble from './MessageBubble.vue'
import PendingApprovalBar from './PendingApprovalBar.vue'

const chatStore = useChatStore()
const { t } = useI18n()
const messagesRef = ref<HTMLElement | null>(null)

// 预构建工具调用配对索引：一次 O(n) 遍历，替代每个 MessageBubble 各自 O(n) 扫描
type ToolPair = { toolCall: ToolCall; toolResult?: ToolResult }
const toolPairsByMsgId = computed(() => {
  const map = new Map<string, ToolPair[]>()
  const msgs = chatStore.currentMessages
  for (let i = 0; i < msgs.length; i++) {
    const m = msgs[i]!
    if (m.role !== 'assistant' || !(m as any).tool_calls?.length) continue
    const pairs: ToolPair[] = []
    for (const tc of (m as any).tool_calls) {
      const fn = tc.function
      let args: Record<string, unknown> = {}
      try { args = fn?.arguments ? JSON.parse(fn.arguments) : tc.arguments || {} } catch {}
      const toolCall: ToolCall = { requestId: tc.id, name: fn?.name || tc.name || 'unknown', arguments: args }
      let toolResult: ToolResult | undefined
      for (let j = i + 1; j < msgs.length; j++) {
        const n = msgs[j]!
        if (n.role !== 'tool') break
        if ((n as any).tool_call_id === tc.id) {
          let success = true
          try { success = JSON.parse(n.content).success !== false } catch {}
          toolResult = { requestId: (n as any).tool_call_id || '', tool: (n as any).name || 'unknown', success, content: n.content }
          break
        }
      }
      pairs.push({ toolCall, toolResult })
    }
    map.set(m.id, pairs)
  }
  return map
})

// S15-E-P0-3（E6）：隐藏 role:'tool' 消息；并隐藏「无正文且无工具卡片」的 assistant
// 消息（取消/中断的工具轮在会话内无 tool_calls → 渲染成『ZaoWu+时间戳』空回复）。
// 配对遍历仍读 chatStore.currentMessages 全量数据（MessageBubble 数据层不受影响）。
const visibleMessages = computed(() =>
  chatStore.currentMessages.filter((m) => {
    if (m.role === 'tool') return false
    if (m.role === 'user') return true
    if (m.role !== 'assistant') return true
    if (m.content && m.content.trim()) return true
    // 正在流式生成的消息保留（可能暂无正文/工具卡片，但需实时展示）
    if (chatStore.isStreaming && chatStore.streamingMessageId === m.id) return true
    // assistant 无正文：有工具卡片则保留（卡片即内容），两者皆无 → 空回复，隐藏
    return (toolPairsByMsgId.value.get(m.id)?.length ?? 0) > 0
  })
)

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

watch(
  () => chatStore.currentMessages.length,
  () => scrollToBottom()
)

watch(
  () => chatStore.currentMessages[chatStore.currentMessages.length - 1]?.content,
  () => scrollToBottom()
)

onMounted(() => {
  chatStore.init()
})
</script>

<template>
  <div class="chat-panel">
    <ChatToolbar />

    <div v-if="chatStore.currentMessages.length === 0" class="chat-empty">
      <div class="empty-icon">
        <MessageSquarePlus :size="40" />
      </div>
      <h3 class="empty-title">{{ t('chat.welcomeTitle') }}</h3>
      <p class="empty-desc">{{ t('chat.welcomeDesc') }}</p>
      <div v-if="!chatStore.hasProvider" class="empty-hint">
        <span>{{ t('chat.setupHint') }}</span>
      </div>
    </div>

    <div v-else ref="messagesRef" class="chat-messages">
      <MessageBubble
        v-for="msg in visibleMessages"
        :key="msg.id"
        :message="msg"
        :tool-pairs="toolPairsByMsgId.get(msg.id)"
        :is-streaming="chatStore.isStreaming && chatStore.streamingMessageId === msg.id && msg.role === 'assistant'"
      />
    </div>

    <!-- 阶段 C10: 全局审批浮层 — 待确认工具调用固定显示在输入框上方，
         不依赖消息气泡位置（原交互需滚动+展开卡片才能批准） -->
    <PendingApprovalBar />

    <ChatInput />
  </div>
</template>

<style scoped>
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chat-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 24px;
}

.empty-icon {
  color: var(--text-tertiary);
  opacity: 0.5;
  margin-bottom: 8px;
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.empty-desc {
  font-size: 13px;
  color: var(--text-tertiary);
  text-align: center;
  max-width: 300px;
  line-height: 1.5;
  margin: 0;
}

.empty-hint {
  margin-top: 12px;
  padding: 8px 14px;
  background: var(--accent-muted);
  border: 1px solid var(--accent);
  border-radius: 8px;
  font-size: 12px;
  color: var(--accent);
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}
</style>
