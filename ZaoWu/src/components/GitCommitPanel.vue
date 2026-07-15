<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'

const { t } = useI18n()
const gitStore = useGitStore()

const message = ref('')
const feedback = ref('')

const canCommit = computed(() => message.value.trim().length > 0 && !gitStore.isCommitting)
const hasStaged = computed(() => gitStore.stagedChanges.length > 0)

async function handleCommit() {
  if (!canCommit.value) return
  const result = await gitStore.commit(message.value.trim())
  if (result.ok) {
    message.value = ''
    feedback.value = t('git.commitSuccess', { hash: result.hash || '' })
    setTimeout(() => { feedback.value = '' }, 3000)
  } else {
    feedback.value = result.error || t('git.commitFailed')
  }
}

async function handlePush() {
  feedback.value = t('git.pushing')
  const result = await gitStore.push()
  feedback.value = result.ok ? (result.output || 'OK') : (result.error || 'push failed')
  setTimeout(() => { feedback.value = '' }, 5000)
}

async function handlePull() {
  feedback.value = t('git.pulling')
  const result = await gitStore.pull()
  if (result.hasConflicts) {
    feedback.value = t('git.conflictsDesc')
  } else {
    feedback.value = result.ok ? (result.output || 'OK') : (result.error || 'pull failed')
  }
  setTimeout(() => { feedback.value = '' }, 5000)
}
</script>

<template>
  <div class="commit-panel">
    <div class="commit-header">
      <span class="commit-title">{{ t('git.commitMessage') }}</span>
      <span v-if="!gitStore.hasProject" class="commit-hint">{{ t('git.noProject') }}</span>
    </div>
    <textarea
      v-model="message"
      class="commit-input"
      :placeholder="t('git.commitPlaceholder')"
      :disabled="!gitStore.hasProject"
      maxlength="200"
      rows="4"
    />
    <div class="commit-actions">
      <button
        class="commit-btn push"
        :disabled="!gitStore.hasProject || gitStore.isLoading"
        :title="t('git.push')"
        @click="handlePush"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 2v6M3 5l3-3 3 3M2 10h8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        {{ t('git.push') }}
      </button>
      <button
        class="commit-btn pull"
        :disabled="!gitStore.hasProject || gitStore.isLoading"
        :title="t('git.pull')"
        @click="handlePull"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 10V4M3 7l3 3 3-3M2 2h8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        {{ t('git.pull') }}
      </button>
      <button
        class="commit-btn commit"
        :disabled="!canCommit || !hasStaged"
        @click="handleCommit"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M9 4l-4 4-2-2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        {{ gitStore.isCommitting ? t('git.committing') : t('git.commit') }}
      </button>
    </div>
    <div v-if="feedback" class="commit-feedback" :class="{ error: feedback.includes('fail') || feedback.includes('error') }">
      {{ feedback }}
    </div>
  </div>
</template>

<style scoped>
.commit-panel {
  display: flex;
  flex-direction: column;
  padding: 12px;
  height: 100%;
  overflow: hidden;
}

.commit-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.commit-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.commit-hint {
  font-size: 11px;
  color: var(--text-tertiary);
}

.commit-input {
  flex: 1;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--text-primary);
  font-size: 13px;
  font-family: inherit;
  resize: none;
  outline: none;
  line-height: 1.5;
}

.commit-input:focus {
  border-color: var(--accent);
}

.commit-input::placeholder {
  color: var(--text-tertiary);
}

.commit-input:disabled {
  opacity: 0.4;
}

.commit-actions {
  display: flex;
  gap: 6px;
  margin-top: 10px;
}

.commit-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition);
}

.commit-btn:disabled {
  opacity: 0.3;
  cursor: default;
}

.commit-btn.push,
.commit-btn.pull {
  background: var(--bg-glass);
  color: var(--text-secondary);
}

.commit-btn.push:hover:not(:disabled),
.commit-btn.pull:hover:not(:disabled) {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.commit-btn.commit {
  background: var(--accent-muted);
  color: var(--accent);
  margin-left: auto;
}

.commit-btn.commit:hover:not(:disabled) {
  background: var(--accent);
  color: #fff;
}

.commit-feedback {
  margin-top: 8px;
  padding: 6px 10px;
  background: var(--bg-glass);
  border-radius: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  max-height: 60px;
  overflow-y: auto;
}

.commit-feedback.error {
  color: var(--danger);
}
</style>
