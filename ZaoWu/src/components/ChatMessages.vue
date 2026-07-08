<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from '@/i18n'
import type { Message } from '@/types'

const { t } = useI18n()

const messages = ref<Message[]>([
  {
    id: '1',
    role: 'assistant',
    content: t('chat.helloMessage'),
    timestamp: Date.now() - 60000,
  },
  {
    id: '2',
    role: 'user',
    content: t('chat.userMessage'),
    timestamp: Date.now() - 45000,
  },
  {
    id: '3',
    role: 'assistant',
    content: t('chat.assistantMessage'),
    timestamp: Date.now() - 30000,
  },
])
</script>

<template>
  <div class="chat-messages">
    <div class="messages-list">
      <div
        v-for="msg in messages"
        :key="msg.id"
        class="message-row"
        :class="msg.role"
      >
        <div v-if="msg.role === 'assistant'" class="avatar">
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <circle cx="9" cy="9" r="8" stroke="currentColor" stroke-width="1.5"/>
            <path d="M6 8.5l2 2 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <div class="bubble" :class="msg.role">
          {{ msg.content }}
        </div>
      </div>
    </div>
    <div class="scroll-bottom"></div>
  </div>
</template>

<style scoped>
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.message-row.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  flex-shrink: 0;
}

.bubble {
  max-width: 75%;
  padding: 10px 14px;
  font-size: 13.5px;
  line-height: 1.6;
  border-radius: 14px;
  word-break: break-word;
  white-space: pre-wrap;
}

.bubble.assistant {
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  color: var(--text-primary);
  border-bottom-left-radius: 4px;
}

.bubble.user {
  background: var(--accent-muted);
  border: 1px solid var(--border-glass);
  color: var(--text-primary);
  border-bottom-right-radius: 4px;
}
</style>
