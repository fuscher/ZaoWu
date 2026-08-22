<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'

const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const gitStore = useGitStore()
const tags = ref<string[]>([])
const newName = ref('')
const newMessage = ref('')
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  await loadTags()
})

async function loadTags() {
  loading.value = true
  const result = await gitStore.fetchTags()
  tags.value = result.tags || []
  loading.value = false
}

async function handleCreate() {
  if (!newName.value.trim()) return
  error.value = ''
  const result = await gitStore.createTag(newName.value.trim(), newMessage.value.trim() || undefined)
  if (result.ok) {
    newName.value = ''
    newMessage.value = ''
    await loadTags()
  } else {
    error.value = result.error || t('git.createTagFailed')
  }
}
</script>

<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog">
      <div class="dialog-header">
        <span class="dialog-title">{{ t('git.tags') }}</span>
        <button class="dialog-close" @click="emit('close')">×</button>
      </div>
      <div class="dialog-body">
        <div class="tag-create">
          <input v-model="newName" :placeholder="t('git.tagName')" class="tag-input" @keydown.enter="handleCreate" />
          <input v-model="newMessage" :placeholder="t('git.tagMessage')" class="tag-input" @keydown.enter="handleCreate" />
          <button class="tag-create-btn" :disabled="!newName.trim()" @click="handleCreate">{{ t('git.createTag') }}</button>
        </div>
        <div v-if="error" class="tag-error">{{ error }}</div>
        <div v-if="loading" class="tag-loading">{{ t('git.loading') }}</div>
        <div v-else-if="tags.length === 0" class="tag-empty">{{ t('git.noTags') }}</div>
        <div v-else class="tag-list">
          <div v-for="tag in tags" :key="tag" class="tag-item">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 3l4 4 4-4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
            <span class="tag-name">{{ tag }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border-glass);
  border-radius: 12px;
  width: 400px;
  max-height: 60vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.3);
}
.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-subtle);
}
.dialog-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.dialog-close {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
}
.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
.tag-create {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.tag-input {
  flex: 1;
  min-width: 0;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
}
.tag-input:focus {
  border-color: var(--accent);
}
.tag-create-btn {
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: var(--accent-muted);
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
}
.tag-create-btn:disabled {
  opacity: 0.3;
  cursor: default;
}
.tag-error {
  color: var(--danger);
  font-size: 11px;
  margin-bottom: 8px;
}
.tag-loading, .tag-empty {
  text-align: center;
  color: var(--text-tertiary);
  padding: 20px;
  font-size: 12px;
}
.tag-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.tag-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-primary);
}
.tag-item:hover {
  background: var(--bg-glass-hover);
}
.tag-name {
  font-family: Consolas, Monaco, monospace;
}
</style>
