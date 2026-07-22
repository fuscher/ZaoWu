<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import { User, Bot } from '@lucide/vue'
import { useCommunityStore } from '@/stores/community'
import { useChatStore } from '@/stores/chat'
import type { Message, ToolCall, ToolResult } from '@/types'
import ToolCallCard from './ToolCallCard.vue'

const props = defineProps<{
  message: Message
  isStreaming?: boolean
  /** Optional collaboration sender name */
  senderName?: string
}>()

const communityStore = useCommunityStore()
const chatStore = useChatStore()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const renderedContent = computed(() => {
  if (!props.message.content) return ''
  return md.render(props.message.content)
})

/**
 * Stage 9: 从已持久化的消息中配对还原工具调用+结果卡片。
 *
 * 修复点：
 * - F06: 将分开存储的 tool_call（assistant 消息）和 tool 结果（tool 消息）按
 *   tool_call_id 合并为一张卡片，而非各自独立渲染。
 * - F09: tool 角色消息的 content 不再通过 Markdown 渲染，避免与卡片双重显示。
 */
const pairedToolCalls = computed(() => {
  type Pair = { toolCall: ToolCall; toolResult?: ToolResult }
  const pairs: Pair[] = []

  if (props.message.role !== 'assistant' || !props.message.tool_calls) return pairs

  // 查找后续的 tool 结果消息（它们紧跟在 assistant 消息后面）
  const allMessages = chatStore.currentMessages
  const msgIndex = allMessages.findIndex((m) => m.id === props.message.id)
  if (msgIndex === -1) return pairs

  for (const tc of props.message.tool_calls) {
    const fn = (tc as any).function
    let args: Record<string, unknown> = {}
    try {
      args = fn?.arguments ? JSON.parse(fn.arguments) : (tc as any).arguments || {}
    } catch {
      args = {}
    }

    const toolCall: ToolCall = {
      requestId: tc.id,
      name: fn?.name || (tc as any).name || 'unknown',
      arguments: args,
    }

    // 在后续消息中查找匹配的 tool 结果（按 tool_call_id 配对）
    let toolResult: ToolResult | undefined
    for (let i = msgIndex + 1; i < allMessages.length; i++) {
      const m = allMessages[i]
      if (!m) break
      if (m.role !== 'tool') break
      if (m.tool_call_id === tc.id) {
        let success = true
        try {
          const parsed = JSON.parse(m.content)
          success = parsed.success !== false
        } catch {
          success = true
        }
        toolResult = {
          requestId: m.tool_call_id || '',
          tool: m.name || 'unknown',
          success,
          content: m.content,
        }
        break
      }
    }
    pairs.push({ toolCall, toolResult })
  }

  return pairs
})

const isUser = computed(() => props.message.role === 'user')
const timeStr = computed(() => {
  const d = new Date(props.message.timestamp)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
})

/** Display name for messages from other collaboration users */
const displayName = computed(() => {
  if (isUser.value && props.senderName) return props.senderName
  if (isUser.value && communityStore.isInRoom && props.message.role === 'user') {
    return communityStore.currentUser?.name ?? 'You'
  }
  return isUser.value ? 'You' : 'AI'
})
</script>

<template>
  <div class="message-bubble" :class="{ user: isUser, assistant: !isUser }">
    <div class="avatar">
      <User v-if="isUser" :size="16" />
      <Bot v-else :size="16" />
    </div>
    <div class="bubble-body">
      <div class="bubble-header">
        <span class="role-name">{{ displayName }}</span>
        <span class="time">{{ timeStr }}</span>
        <span v-if="message.model && !isUser" class="model-tag">{{ message.model }}</span>
      </div>
      <div v-if="isUser" class="content-text">{{ message.content }}</div>
      <!-- F09: tool 角色消息的 content 不再通过 Markdown 渲染，结果仅通过配对卡片显示 -->
      <div v-else-if="message.role === 'tool'" class="content-text tool-result-text" />
      <div v-else class="content-md" v-html="renderedContent" />
      <!-- Stage 9: 实时工具调用卡片（仅当前正在流式生成的消息） -->
      <div
        v-if="!isUser && isStreaming && chatStore.streamingMessageId === message.id"
        class="tool-calls"
      >
        <ToolCallCard
          v-for="[requestId, result] in chatStore.toolResultsFor(message.id)"
          :key="requestId"
          :tool-call="chatStore.toolCallsFor(message.id).get(requestId)"
          :tool-result="result"
          :requires-approval="chatStore.pendingFor(message.id).has(requestId)"
          @approve="chatStore.confirmTool($event, true)"
          @reject="chatStore.confirmTool($event, false)"
        />
        <ToolCallCard
          v-for="[requestId, toolCall] in chatStore.pendingFor(message.id)"
          :key="`pending-${requestId}`"
          :tool-call="toolCall"
          :requires-approval="true"
          @approve="chatStore.confirmTool($event, true)"
          @reject="chatStore.confirmTool($event, false)"
        />
      </div>
      <!-- Stage 9: 历史工具调用配对卡片（合并 call + result） -->
      <div v-if="!isUser && pairedToolCalls.length > 0" class="tool-calls">
        <ToolCallCard
          v-for="(pair, index) in pairedToolCalls"
          :key="index"
          :tool-call="pair.toolCall"
          :tool-result="pair.toolResult"
        />
      </div>
      <div v-if="isStreaming && !isUser" class="streaming-indicator">
        <span class="dot" /><span class="dot" /><span class="dot" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-bubble {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.message-bubble.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.user .avatar {
  background: var(--accent-hover);
  color: #fff;
}

.assistant .avatar {
  background: var(--bg-glass);
  color: var(--text-secondary);
  border: 1px solid var(--border-glass);
}

.bubble-body {
  min-width: 0;
  max-width: 80%;
}

.user .bubble-body {
  text-align: right;
}

.bubble-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.user .bubble-header {
  flex-direction: row-reverse;
}

.role-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.time {
  font-size: 11px;
  color: var(--text-tertiary);
}

.model-tag {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 1px 6px;
  border-radius: 4px;
}

.content-text {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.content-md {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-primary);
  word-break: break-word;
}

.content-md :deep(p) {
  margin: 0 0 8px;
}

.content-md :deep(p:last-child) {
  margin-bottom: 0;
}

.content-md :deep(code) {
  background: var(--bg-glass);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12.5px;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
}

.content-md :deep(pre) {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  margin: 8px 0;
}

.content-md :deep(pre code) {
  background: none;
  padding: 0;
  font-size: 12.5px;
}

.content-md :deep(ul),
.content-md :deep(ol) {
  padding-left: 20px;
  margin: 4px 0;
}

.content-md :deep(blockquote) {
  border-left: 3px solid var(--accent);
  padding-left: 12px;
  color: var(--text-secondary);
  margin: 8px 0;
}

.content-md :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
}

.content-md :deep(th),
.content-md :deep(td) {
  border: 1px solid var(--border-subtle);
  padding: 6px 10px;
  text-align: left;
  font-size: 12.5px;
}

.content-md :deep(th) {
  background: var(--bg-glass);
}

.streaming-indicator {
  display: flex;
  gap: 4px;
  padding-top: 4px;
}

.tool-calls {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-tertiary);
  animation: pulse 1.4s infinite;
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}
</style>
