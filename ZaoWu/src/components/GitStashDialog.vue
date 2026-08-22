<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'
import ConfirmDialog from './ConfirmDialog.vue'

const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const gitStore = useGitStore()

const stashMessage = ref('')
const isStashing = ref(false)
const feedback = ref('')
const showDropConfirm = ref(false)
const dropTarget = ref(-1)

onMounted(() => {
  gitStore.fetchStashes()
})

async function handleStash() {
  isStashing.value = true
  try {
    const result = await gitStore.stash(stashMessage.value.trim() || undefined)
    if (result.ok) {
      stashMessage.value = ''
      feedback.value = t('git.stashSuccess')
      await gitStore.fetchStashes()
      setTimeout(() => { feedback.value = '' }, 3000)
    } else {
      feedback.value = result.error || 'stash failed'
    }
  } finally {
    isStashing.value = false
  }
}

async function handlePop(index: number) {
  const result = await gitStore.stashPop(index)
  if (result.ok) {
    feedback.value = t('git.stashPopSuccess')
    await gitStore.fetchStashes()
    setTimeout(() => { feedback.value = '' }, 3000)
  } else {
    feedback.value = result.error || 'stash pop failed'
  }
}

async function handleApply(index: number) {
  const result = await gitStore.stashApply(index)
  if (result.ok) {
    feedback.value = t('git.stashPopSuccess')
    await gitStore.fetchStashes()
    setTimeout(() => { feedback.value = '' }, 3000)
  } else {
    feedback.value = result.error || 'stash apply failed'
  }
}

function confirmDrop(index: number) {
  dropTarget.value = index
  showDropConfirm.value = true
}

async function executeDrop() {
  showDropConfirm.value = false
  const idx = dropTarget.value
  if (idx < 0) return
  const result = await gitStore.stashDrop(idx)
  if (result.ok) {
    await gitStore.fetchStashes()
  } else {
    feedback.value = result.error || 'stash drop failed'
  }
  dropTarget.value = -1
}
</script>

<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog">
      <div class="dialog-header">
        <span class="dialog-title">{{ t('git.stashList') }}</span>
        <button class="dialog-close" @click="emit('close')">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
      </div>

      <!-- 新建暂存 -->
      <div class="stash-input-row">
        <input
          v-model="stashMessage"
          class="stash-input"
          :placeholder="t('git.stashMessagePlaceholder')"
          @keydown.enter="handleStash"
        />
        <button class="stash-save-btn" :disabled="isStashing" @click="handleStash">
          {{ isStashing ? '...' : t('git.stash') }}
        </button>
      </div>

      <!-- 暂存列表 -->
      <div class="stash-body">
        <div v-if="gitStore.stashList.length === 0" class="stash-empty">
          {{ t('git.noStashes') }}
        </div>
        <div v-for="s in gitStore.stashList" :key="s.index" class="stash-item">
          <span class="stash-index">stash@{ {{ s.index }} }</span>
          <span class="stash-message">{{ s.message }}</span>
          <div class="stash-actions">
            <button class="stash-action-btn" :title="t('git.stashPop')" @click="handlePop(s.index)">
              {{ t('git.stashPop') }}
            </button>
            <button class="stash-action-btn" :title="t('git.stashApply')" @click="handleApply(s.index)">
              {{ t('git.stashApply') }}
            </button>
            <button class="stash-action-btn danger" :title="t('git.stashDrop')" @click="confirmDrop(s.index)">
              {{ t('git.stashDrop') }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="feedback" class="stash-feedback">{{ feedback }}</div>
    </div>
  </div>

  <ConfirmDialog
    :visible="showDropConfirm"
    :title="t('git.stashDrop')"
    :message="t('git.stashConfirmDrop')"
    @confirm="executeDrop"
    @cancel="showDropConfirm = false"
  />
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
  width: 440px;
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
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
}

.dialog-close:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.stash-input-row {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.stash-input {
  flex: 1;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 8px 12px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.stash-input:focus {
  border-color: var(--accent);
}

.stash-input::placeholder {
  color: var(--text-tertiary);
}

.stash-save-btn {
  padding: 8px 14px;
  border: none;
  border-radius: 8px;
  background: var(--accent-muted);
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--transition);
}

.stash-save-btn:hover:not(:disabled) {
  background: var(--accent);
  color: #fff;
}

.stash-save-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.stash-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.stash-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
}

.stash-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  transition: background var(--transition);
}

.stash-item:hover {
  background: var(--bg-glass-hover);
}

.stash-index {
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: Consolas, Monaco, monospace;
  flex-shrink: 0;
}

.stash-message {
  font-size: 13px;
  color: var(--text-primary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stash-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity var(--transition);
}

.stash-item:hover .stash-actions {
  opacity: 1;
}

.stash-action-btn {
  padding: 3px 8px;
  border: 1px solid var(--border-glass);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all var(--transition);
}

.stash-action-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.stash-action-btn.danger:hover {
  background: var(--danger-muted, rgba(185, 28, 28, 0.1));
  color: var(--danger);
  border-color: var(--danger-muted, rgba(185, 28, 28, 0.2));
}

.stash-feedback {
  padding: 8px 16px;
  font-size: 11px;
  color: var(--text-secondary);
  border-top: 1px solid var(--border-subtle);
}
</style>
