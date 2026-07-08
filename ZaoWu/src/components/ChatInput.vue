<script setup lang="ts">
import { ref } from 'vue'
import { Send, Square } from '@lucide/vue'
import { useI18n } from '@/i18n'

const { t } = useI18n()
const input = ref('')
const isComposing = ref(false)

function handleSend() {
  if (!input.value.trim() || isComposing.value) return
  input.value = ''
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
      <button class="send-btn" :class="{ active: input.trim() }" @click="handleSend">
        <Send :size="16" />
      </button>
    </div>
    <div class="input-footer">
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
  align-items: flex-end;
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

.input-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
}

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
}
</style>
