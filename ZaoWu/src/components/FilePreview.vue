<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { X, Save, RotateCcw } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useEditorStore } from '@/stores/editor'

const store = useEditorStore()
const { t } = useI18n()
const revertTitle = computed(() => t('filePreview.revert'))
const saveTitle = computed(() => t('filePreview.save'))
const closeTitle = computed(() => t('filePreview.close'))
const textareaRef = ref<HTMLTextAreaElement | null>(null)

function handleInput(e: Event) {
  const target = e.target as HTMLTextAreaElement
  store.updateContent(target.value)
}

function handleKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault()
    store.saveFile()
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="file-preview">
    <div class="preview-header">
      <div class="header-left">
        <span class="header-filename">{{ store.fileName }}</span>
        <span v-if="store.isDirty" class="dirty-dot"></span>
      </div>
      <div class="header-actions">
        <button class="header-btn" :disabled="!store.isDirty" :title="revertTitle" @click="store.revertFile()">
          <RotateCcw :size="14" />
        </button>
        <button class="header-btn primary" :disabled="!store.isDirty" :title="saveTitle" @click="store.saveFile()">
          <Save :size="14" />
        </button>
        <button class="header-btn" :title="closeTitle" @click="store.closeFile()">
          <X :size="14" />
        </button>
      </div>
    </div>
    <div class="preview-body">
      <div v-if="store.isLoading" class="preview-loading">
        <svg width="16" height="16" viewBox="0 0 16 16" class="spin">
          <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5" fill="none" stroke-dasharray="24 16"/>
        </svg>
      </div>
      <div v-else-if="store.error" class="preview-error">{{ store.error }}</div>
      <textarea
        v-else
        ref="textareaRef"
        class="editor"
        :value="store.fileContent"
        spellcheck="false"
        @input="handleInput"
      />
    </div>
  </div>
</template>

<style scoped>
.file-preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-bottom: 1px solid var(--border-glass);
  flex-shrink: 0;
  min-height: 30px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.header-filename {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dirty-dot {
  width: 8px;
  height: 8px;
  background: var(--accent);
  border-radius: 50%;
  flex-shrink: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.header-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all 0.15s;
}

.header-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.header-btn.primary:hover {
  color: var(--accent);
}

.header-btn:disabled {
  opacity: 0.3;
  cursor: default;
}

.preview-body {
  flex: 1;
  overflow: hidden;
  position: relative;
}

.preview-loading,
.preview-error {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-tertiary);
  font-size: 13px;
}

.preview-error {
  color: var(--danger);
}

.editor {
  width: 100%;
  height: 100%;
  padding: 12px 16px;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--text-primary);
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  tab-size: 4;
  white-space: pre;
  overflow-wrap: normal;
  overflow: auto;
}

.editor:focus {
  background: var(--bg-glass);
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
