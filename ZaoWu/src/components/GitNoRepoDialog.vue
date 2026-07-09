<script setup lang="ts">
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'

const emit = defineEmits<{ close: []; init: [] }>()
const { t } = useI18n()
const gitStore = useGitStore()
</script>

<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog">
      <div class="dialog-body">
        <svg class="dialog-icon" width="32" height="32" viewBox="0 0 14 14" fill="none"><path d="M7 1v7M7 8l-2-2M7 8l2-2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="3.5" cy="11.5" r="1.5" stroke="currentColor" stroke-width="1.2" fill="none"/><circle cx="10.5" cy="11.5" r="1.5" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
        <div class="dialog-title">{{ t('git.initGitPrompt', { name: gitStore.selectedProject?.name || '' }) }}</div>
      </div>
      <div class="dialog-footer">
        <button class="dialog-btn secondary" @click="emit('close')">{{ t('git.close') }}</button>
        <button class="dialog-btn primary" @click="emit('init')">{{ t('git.initGit') }}</button>
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
  width: 380px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.3);
}

.dialog-body {
  padding: 24px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 10px;
}

.dialog-icon {
  color: var(--text-tertiary);
}

.dialog-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border-subtle);
}

.dialog-btn {
  padding: 7px 16px;
  border-radius: 8px;
  border: none;
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition);
}

.dialog-btn.secondary {
  background: var(--bg-glass);
  color: var(--text-secondary);
}

.dialog-btn.secondary:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.dialog-btn.primary {
  background: var(--accent-muted);
  color: var(--accent);
}

.dialog-btn.primary:hover {
  background: var(--accent);
  color: #fff;
}
</style>
