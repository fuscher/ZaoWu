<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'

const emit = defineEmits<{ close: []; created: [] }>()
const { t } = useI18n()
const gitStore = useGitStore()

const branchName = ref('')
const switchToNew = ref(true)
const isCreating = ref(false)
const error = ref('')

async function handleCreate() {
  const name = branchName.value.trim()
  if (!name) return
  // 前端校验
  if (name.includes('/') || name.includes('..') || name.startsWith('-')) {
    error.value = t('git.invalidBranchName')
    return
  }
  isCreating.value = true
  error.value = ''
  try {
    const result = await gitStore.createBranch(name, switchToNew.value)
    if (result.ok) {
      emit('created')
    } else {
      error.value = result.error || t('git.branchCreateFailed')
    }
  } finally {
    isCreating.value = false
  }
}
</script>

<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog">
      <div class="dialog-header">
        <span class="dialog-title">{{ t('git.createBranch') }}</span>
        <button class="dialog-close" @click="emit('close')">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
      </div>
      <div class="dialog-body">
        <label class="field-label">{{ t('git.branchName') }}</label>
        <input
          v-model="branchName"
          class="field-input"
          :placeholder="t('git.branchNamePlaceholder')"
          autofocus
          @keydown.enter="handleCreate"
        />
        <label class="field-checkbox">
          <input type="checkbox" v-model="switchToNew" />
          <span>{{ t('git.switchToNewBranch') }}</span>
        </label>
        <div v-if="error" class="field-error">{{ error }}</div>
      </div>
      <div class="dialog-footer">
        <button class="btn-cancel" @click="emit('close')">{{ t('git.close') }}</button>
        <button class="btn-confirm" :disabled="!branchName.trim() || isCreating" @click="handleCreate">
          {{ isCreating ? '...' : t('git.createBranch') }}
        </button>
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
  z-index: 1001;
}

.dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border-glass);
  border-radius: 12px;
  width: 360px;
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

.dialog-body {
  padding: 16px 20px;
}

.field-label {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.field-input {
  width: 100%;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 8px 12px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
}

.field-input:focus {
  border-color: var(--accent);
}

.field-input::placeholder {
  color: var(--text-tertiary);
}

.field-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}

.field-checkbox input {
  accent-color: var(--accent);
}

.field-error {
  margin-top: 8px;
  font-size: 12px;
  color: var(--danger);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border-subtle);
}

.btn-cancel {
  padding: 6px 14px;
  border: 1px solid var(--border-glass);
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
}

.btn-cancel:hover {
  background: var(--bg-glass-hover);
}

.btn-confirm {
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
  cursor: pointer;
}

.btn-confirm:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn-confirm:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>
