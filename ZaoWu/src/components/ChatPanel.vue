<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { MessageSquarePlus } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'
import ChatToolbar from './ChatToolbar.vue'
import ChatInput from './ChatInput.vue'
import MessageBubble from './MessageBubble.vue'

const chatStore = useChatStore()
const { t } = useI18n()
const messagesRef = ref<HTMLElement | null>(null)

// S15-E-P0-3（E6）：隐藏 role:'tool' 消息（重载后避免空气泡）；
// 配对遍历仍读 chatStore.currentMessages 全量数据（MessageBubble 数据层不受影响）
const visibleMessages = computed(() =>
  chatStore.currentMessages.filter((m) => m.role !== 'tool')
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
        :is-streaming="chatStore.isStreaming && chatStore.streamingMessageId === msg.id && msg.role === 'assistant'"
      />
    </div>

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
