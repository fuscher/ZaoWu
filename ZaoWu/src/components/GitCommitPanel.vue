<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'

const { t } = useI18n()
const gitStore = useGitStore()

const message = ref('')
const feedback = ref('')
const isAmend = ref(false)
const isPushing = ref(false)
const isPulling = ref(false)
const isFetching = ref(false)
const isError = ref(false)

const canCommit = computed(() => message.value.trim().length > 0 && !gitStore.isCommitting)
const hasStaged = computed(() => gitStore.stagedChanges.length > 0)

// 同步状态文案
const syncLabel = computed(() => {
  const { ahead, behind } = gitStore.fetchInfo
  if (ahead === 0 && behind === 0) return t('git.synced')
  const parts: string[] = []
  if (ahead > 0) parts.push(t('git.aheadCount', { count: ahead }))
  if (behind > 0) parts.push(t('git.behindCount', { count: behind }))
  return parts.join(', ')
})

const syncClass = computed(() => {
  const { ahead, behind } = gitStore.fetchInfo
  if (ahead === 0 && behind === 0) return 'synced'
  if (behind > 0) return 'behind'
  return 'ahead'
})

// 切换 amend 模式，预填上一次提交消息
function toggleAmend() {
  isAmend.value = !isAmend.value
  if (isAmend.value && !message.value && gitStore.commits.length > 0) {
    message.value = gitStore.commits[0]?.message ?? ''
  }
}

async function handleCommit() {
  if (!canCommit.value) return
  const result = await gitStore.commit(message.value.trim(), isAmend.value)
  isError.value = !result.ok
  if (result.ok) {
    message.value = ''
    isAmend.value = false
    feedback.value = t('git.commitSuccess', { hash: result.hash || '' })
    setTimeout(() => { feedback.value = '' }, 3000)
  } else {
    feedback.value = result.error || t('git.commitFailed')
  }
}

async function handleUndoCommit() {
  const result = await gitStore.undoCommit()
  isError.value = !result.ok
  if (result.ok) {
    feedback.value = t('git.undoCommitSuccess')
  } else {
    feedback.value = result.error || t('git.undoCommitFailed')
  }
  setTimeout(() => { feedback.value = '' }, 3000)
}

async function handlePush() {
  isPushing.value = true
  feedback.value = t('git.pushing')
  try {
    const result = await gitStore.push()
    isError.value = !result.ok
    feedback.value = result.ok ? (result.output || 'OK') : (result.error || 'push failed')
    setTimeout(() => { feedback.value = '' }, 5000)
  } finally {
    isPushing.value = false
  }
}

async function handlePull() {
  isPulling.value = true
  feedback.value = t('git.pulling')
  try {
    const result = await gitStore.pull()
    if (result.hasConflicts) {
      isError.value = true
      feedback.value = t('git.conflictsDesc')
    } else {
      isError.value = !result.ok
      feedback.value = result.ok ? (result.output || 'OK') : (result.error || 'pull failed')
    }
    setTimeout(() => { feedback.value = '' }, 5000)
  } finally {
    isPulling.value = false
  }
}

async function handleFetch() {
  isFetching.value = true
  try {
    const result = await gitStore.fetchRemote()
    isError.value = !result.ok
    if (result.ok) {
      feedback.value = t('git.fetchSuccess')
    } else {
      feedback.value = result.error || 'fetch failed'
    }
    setTimeout(() => { feedback.value = '' }, 3000)
  } finally {
    isFetching.value = false
  }
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
    <!-- 同步状态 -->
    <div v-if="gitStore.hasProject && gitStore.hasGitRepo" class="sync-status" :class="syncClass">
      <span class="sync-dot" />
      {{ syncLabel }}
    </div>
    <div class="commit-actions">
      <button
        class="commit-btn fetch"
        :disabled="!gitStore.hasProject || isFetching"
        :title="t('git.fetch')"
        @click="handleFetch"
      >
        <span v-if="isFetching" class="spinner" />
        <svg v-else width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 10V2M3 5l3 3 3-3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        {{ isFetching ? t('git.fetching') : t('git.fetch') }}
      </button>
      <button
        class="commit-btn push"
        :disabled="!gitStore.hasProject || isPushing || gitStore.isCommitting"
        :title="t('git.push')"
        @click="handlePush"
      >
        <span v-if="isPushing" class="spinner" />
        <svg v-else width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 2v6M3 5l3-3 3 3M2 10h8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        {{ isPushing ? t('git.pushing') : t('git.push') }}
      </button>
      <button
        class="commit-btn pull"
        :disabled="!gitStore.hasProject || isPulling || gitStore.isCommitting"
        :title="t('git.pull')"
        @click="handlePull"
      >
        <span v-if="isPulling" class="spinner" />
        <svg v-else width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 10V4M3 7l3 3 3-3M2 2h8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        {{ isPulling ? t('git.pulling') : t('git.pull') }}
      </button>
      <button
        class="commit-btn amend"
        :class="{ active: isAmend }"
        :disabled="!gitStore.hasProject"
        :title="t('git.amendTooltip')"
        @click="toggleAmend"
      >
        {{ t('git.amend') }}
      </button>
      <button
        class="commit-btn commit"
        :disabled="!canCommit || (!hasStaged && !isAmend)"
        @click="handleCommit"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M9 4l-4 4-2-2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        {{ gitStore.isCommitting ? t('git.committing') : t('git.commit') }}
      </button>
      <button
        v-if="gitStore.commits.length >= 2"
        class="commit-btn undo"
        :disabled="!gitStore.hasProject || gitStore.isCommitting"
        :title="t('git.undoCommit')"
        @click="handleUndoCommit"
      >
        {{ t('git.undoCommit') }}
      </button>
    </div>
    <div v-if="feedback" class="commit-feedback" :class="{ error: isError }">
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

.sync-status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.sync-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-tertiary);
}

.sync-status.synced .sync-dot {
  background: var(--success, #22c55e);
}

.sync-status.synced {
  color: var(--success, #22c55e);
}

.sync-status.ahead .sync-dot {
  background: var(--accent);
}

.sync-status.ahead {
  color: var(--accent);
}

.sync-status.behind .sync-dot {
  background: var(--warning, #f59e0b);
}

.sync-status.behind {
  color: var(--warning, #f59e0b);
}

.commit-actions {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
  margin-top: 10px;
}

.commit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 6px 10px;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition);
  white-space: nowrap;
}

.commit-btn:disabled {
  opacity: 0.3;
  cursor: default;
}

.commit-btn.fetch,
.commit-btn.push,
.commit-btn.pull {
  background: var(--bg-glass);
  color: var(--text-secondary);
}

.commit-btn.fetch:hover:not(:disabled),
.commit-btn.push:hover:not(:disabled),
.commit-btn.pull:hover:not(:disabled) {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.commit-btn.amend {
  background: var(--bg-glass);
  color: var(--text-tertiary);
  font-size: 11px;
  padding: 6px 8px;
}

.commit-btn.amend.active {
  background: var(--accent-muted);
  color: var(--accent);
}

.commit-btn.amend:hover:not(:disabled) {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

.commit-btn.commit {
  background: var(--accent-muted);
  color: var(--accent);
  grid-column: 1 / -1;
}

.commit-btn.commit:hover:not(:disabled) {
  background: var(--accent);
  color: #fff;
}

.commit-btn.undo {
  background: var(--bg-glass);
  color: var(--danger, #ef4444);
  grid-column: 1 / -1;
}

.commit-btn.undo:hover:not(:disabled) {
  background: var(--danger-muted, rgba(239, 68, 68, 0.15));
  color: var(--danger, #ef4444);
}

.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--border-glass);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
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
