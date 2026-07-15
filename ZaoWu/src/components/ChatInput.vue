<script setup lang="ts">
import { ref } from 'vue'
import { Send, Square } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'
import ModelSwitcher from './ModelSwitcher.vue'
import ParameterPanel from './ParameterPanel.vue'

const chatStore = useChatStore()
const { t } = useI18n()
const input = ref('')
const isComposing = ref(false)

function handleSend() {
  if (!input.value.trim() || isComposing.value) return
  chatStore.sendMessage(input.value.trim())
  input.value = ''
}

function handleStop() {
  chatStore.stopStreaming()
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="chat-input">
    <div class="input-wrapper">
      <textarea
        v-model="input"
        :placeholder="t('chat.placeholder')"
        rows="1"
        @keydown="handleKeydown"
        @compositionstart="isComposing = true"
        @compositionend="isComposing = false"
        @input="isComposing = false"
      />
      <button
        v-if="chatStore.isStreaming"
        class="stop-btn"
        :title="t('chat.stopGeneration')"
        @click="handleStop"
      >
        <Square :size="14" />
      </button>
      <button v-else class="send-btn" :class="{ active: input.trim() }" @click="handleSend">
        <Send :size="16" />
      </button>
    </div>
    <div class="input-footer">
      <div class="footer-left">
        <ModelSwitcher />
        <ParameterPanel />
      </div>
      <span class="hint">{{ t('chat.shortcutHint') }}</span>
    </div>
  </div>
</template>

<style scoped>
.chat-input {
  padding: 12px 16px;
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.input-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 14px;
  padding: 8px 8px 8px 16px;
  transition: border-color var(--transition);
}

.input-wrapper:focus-within {
  border-color: var(--accent);
}

textarea {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-size: 13.5px;
  font-family: inherit;
  resize: none;
  line-height: 1.5;
  max-height: 120px;
}

textarea::placeholder {
  color: var(--text-tertiary);
}

.send-btn {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  border: none;
  background: var(--bg-glass);
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition);
}

.send-btn.active {
  background: var(--accent);
  color: #fff;
}

.send-btn.active:hover {
  background: var(--accent-hover);
}

.stop-btn {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  border: none;
  background: var(--danger);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition);
  animation: pulse-red 1.5s infinite;
}

.stop-btn:hover {
  background: var(--danger);
  filter: brightness(0.88);
}

@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 0 rgba(201, 42, 42, 0.4); }
  50% { box-shadow: 0 0 0 4px rgba(201, 42, 42, 0); }
}

.input-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 4px;
}

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
}
</style>
