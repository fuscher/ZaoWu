<script setup lang="ts">
import { Plus, Eraser } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'

const chatStore = useChatStore()
const { t } = useI18n()

async function handleNew() {
  await chatStore.createNewConversation()
}

function handleClear() {
  chatStore.clearMessages()
}
</script>

<template>
  <div class="chat-toolbar">
    <div class="toolbar-left">
      <button class="tool-btn" :title="t('chat.newConversation')" @click="handleNew">
        <Plus :size="14" />
      </button>
      <button
        class="tool-btn"
        :title="t('chat.clearMessages')"
        :disabled="!chatStore.currentConversation || chatStore.currentMessages.length === 0"
        @click="handleClear"
      >
        <Eraser :size="14" />
      </button>
    </div>
    <div class="toolbar-center">
      <span v-if="chatStore.currentConversation" class="conv-title">
        {{ chatStore.currentConversation.title }}
      </span>
      <span v-else class="conv-title placeholder">{{ t('chat.noActiveConversation') }}</span>
    </div>
  </div>
</template>

<style scoped>
.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 16px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
  flex-shrink: 0;
  gap: 8px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 4px;
}

.toolbar-center {
  flex: 1;
  text-align: center;
  min-width: 0;
}

.conv-title {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-title.placeholder {
  color: var(--text-tertiary);
}

.tool-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all var(--transition);
}

.tool-btn:hover:not(:disabled) {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

.tool-btn:disabled {
  opacity: 0.3;
  cursor: default;
}
</style>
