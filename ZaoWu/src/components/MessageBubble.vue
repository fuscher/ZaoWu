<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import { User, Bot } from '@lucide/vue'
import { useCommunityStore } from '@/stores/community'
import type { Message } from '@/types'

const props = defineProps<{
  message: Message
  isStreaming?: boolean
  /** Optional collaboration sender name */
  senderName?: string
}>()

const communityStore = useCommunityStore()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const renderedContent = computed(() => {
  if (!props.message.content) return ''
  return md.render(props.message.content)
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
      <div v-else class="content-md" v-html="renderedContent" />
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
