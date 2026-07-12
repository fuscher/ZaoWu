<script setup lang="ts">
import { ref, computed, nextTick, toValue } from 'vue'
import { Send } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { CollaborationUser } from '@/types'
import type { Ref } from 'vue'

const props = defineProps<{
  messages: { userId: string; content: string; timestamp: number }[] | Ref<{ userId: string; content: string; timestamp: number }[]>
  users: CollaborationUser[]
  currentUserId: string
}>()

const emit = defineEmits<{ send: [content: string] }>()
const { t } = useI18n()

const input = ref('')
const chatBodyRef = ref<HTMLElement>()

const rawMessages = computed(() => toValue(props.messages))

const messageList = computed(() =>
  rawMessages.value.map((m) => {
    const user = props.users.find((u) => u.id === m.userId) || {
      id: m.userId,
      name: t('community.unknownUser'),
      color: 'var(--text-tertiary)',
      role: 'observer',
      status: 'offline',
    }
    return { ...m, user }
  }),
)

function send() {
  const text = input.value.trim()
  if (!text) return
  emit('send', text)
  input.value = ''
  nextTick(() => {
    chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' })
  })
}

function formatTime(ts: number) {
  const d = new Date(ts)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}
</script>

<template>
  <div class="community-chat">
    <div ref="chatBodyRef" class="chat-body">
      <div v-if="messageList.length === 0" class="chat-empty">{{ t('community.chatPlaceholder') }}</div>
      <div
        v-for="(msg, idx) in messageList"
        :key="idx"
        class="chat-message"
        :class="{ self: msg.userId === currentUserId }"
      >
        <div class="chat-avatar" :style="{ backgroundColor: msg.user.color }">
          {{ msg.user.name.charAt(0).toUpperCase() }}
        </div>
        <div class="chat-bubble">
          <div class="chat-meta">
            <span class="chat-name">{{ msg.user.name }}</span>
            <span class="chat-time">{{ formatTime(msg.timestamp) }}</span>
          </div>
          <div class="chat-content">{{ msg.content }}</div>
        </div>
      </div>
    </div>
    <div class="chat-input-row">
      <input v-model="input" type="text" :placeholder="t('community.chatInputPlaceholder')" @keydown.enter="send" />
      <button :disabled="!input.trim()" @click="send">
        <Send :size="14" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.community-chat {
  display: flex;
  flex-direction: column;
  width: 260px;
  border-left: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
  flex-shrink: 0;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chat-empty {
  font-size: 12px;
  color: var(--text-tertiary);
  text-align: center;
  margin-top: 20px;
}

.chat-message {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.chat-message.self {
  flex-direction: row-reverse;
}

.chat-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 600;
  color: white;
  flex-shrink: 0;
}

.chat-bubble {
  max-width: calc(100% - 36px);
  background: var(--bg-glass);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 8px 10px;
  box-shadow: var(--shadow-sm);
}

.chat-message.self .chat-bubble {
  background: var(--accent-muted);
  border-color: transparent;
}

.chat-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.chat-name {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
}

.chat-time {
  font-size: 10px;
  color: var(--text-tertiary);
}

.chat-content {
  font-size: 12px;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.chat-input-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px;
  border-top: 1px solid var(--border-subtle);
}

.chat-input-row input {
  flex: 1;
  padding: 7px 10px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  transition: border-color var(--transition);
}

.chat-input-row input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-muted);
}

.chat-input-row button {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all var(--transition);
}

.chat-input-row button:hover:not(:disabled) {
  background: var(--accent-hover);
}

.chat-input-row button:active:not(:disabled) {
  transform: scale(0.95);
}

.chat-input-row button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
