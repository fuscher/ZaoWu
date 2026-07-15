<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'
import ConfirmDialog from './ConfirmDialog.vue'

const { t } = useI18n()
const gitStore = useGitStore()

const batchMode = ref(false)
const selectedFiles = ref<Set<string>>(new Set())
const showDiscardConfirm = ref(false)

const untrackedFiles = computed(() => gitStore.untrackedChanges)
const stagedFiles = computed(() => gitStore.stagedChanges)
const hasChanges = computed(() => untrackedFiles.value.length > 0 || stagedFiles.value.length > 0)

const allSelectable = computed(() => [...untrackedFiles.value, ...stagedFiles.value].map(f => f.path))
const allSelected = computed(() =>
  allSelectable.value.length > 0 && allSelectable.value.every(f => selectedFiles.value.has(f))
)

function toggleSelectAll() {
  if (allSelected.value) {
    selectedFiles.value = new Set()
  } else {
    selectedFiles.value = new Set(allSelectable.value)
  }
}

function toggleFile(path: string) {
  if (selectedFiles.value.has(path)) {
    selectedFiles.value.delete(path)
  } else {
    selectedFiles.value.add(path)
  }
}

function enterBatchMode() {
  batchMode.value = true
  selectedFiles.value = new Set()
}

function exitBatchMode() {
  batchMode.value = false
  selectedFiles.value = new Set()
}

async function stageSelected() {
  const files = [...selectedFiles.value]
  if (files.length === 0) return
  await gitStore.stageFiles(files)
  exitBatchMode()
}

function confirmDiscard() {
  if (selectedFiles.value.size === 0) return
  showDiscardConfirm.value = true
}

async function executeDiscard() {
  showDiscardConfirm.value = false
  const files = [...selectedFiles.value]
  await gitStore.discardFiles(files)
  exitBatchMode()
}
</script>

<template>
  <div class="changes-list">
    <div class="changes-header">
      <span class="changes-title">{{ t('git.changes') }}</span>
      <button
        v-if="!batchMode && hasChanges"
        class="changes-btn"
        @click="enterBatchMode"
      >
        {{ t('git.batchMode') }}
      </button>
      <template v-if="batchMode">
        <button class="changes-btn" @click="toggleSelectAll">
          {{ allSelected ? t('git.deselectAll') : t('git.selectAll') }}
        </button>
        <button
          class="changes-btn accent"
          :disabled="selectedFiles.size === 0"
          @click="stageSelected"
        >
          {{ t('git.stageChanges') }}
        </button>
        <button
          class="changes-btn danger"
          :disabled="selectedFiles.size === 0"
          @click="confirmDiscard"
        >
          {{ t('git.discardChanges') }}
        </button>
        <button class="changes-btn" @click="exitBatchMode">
          {{ t('git.exitBatch') }}
        </button>
      </template>
    </div>

    <div v-if="!hasChanges" class="changes-empty">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6v8M6 10h8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
      <span>{{ t('git.noChanges') }}</span>
    </div>

    <div v-else class="changes-body">
      <template v-if="untrackedFiles.length > 0">
        <div class="changes-section-label">{{ t('git.untrackedChanges') }} ({{ untrackedFiles.length }})</div>
        <div
          v-for="f in untrackedFiles"
          :key="f.path"
          class="changes-file"
          :class="{ selected: batchMode && selectedFiles.has(f.path) }"
          @click="batchMode && toggleFile(f.path)"
        >
          <span v-if="batchMode" class="changes-check">{{ selectedFiles.has(f.path) ? '✓' : '○' }}</span>
          <span class="changes-file-type" :class="f.type">{{ (f.type?.[0] || '?').toUpperCase() }}</span>
          <span class="changes-file-path">{{ f.path }}</span>
        </div>
      </template>

      <template v-if="stagedFiles.length > 0">
        <div class="changes-section-label">{{ t('git.stagedChanges') }} ({{ stagedFiles.length }})</div>
        <div
          v-for="f in stagedFiles"
          :key="f.path"
          class="changes-file staged"
          :class="{ selected: batchMode && selectedFiles.has(f.path) }"
          @click="batchMode && toggleFile(f.path)"
        >
          <span v-if="batchMode" class="changes-check">{{ selectedFiles.has(f.path) ? '✓' : '○' }}</span>
          <span class="changes-file-type" :class="f.type">{{ (f.type?.[0] || '?').toUpperCase() }}</span>
          <span class="changes-file-path">{{ f.path }}</span>
        </div>
      </template>
    </div>

    <ConfirmDialog
      :visible="showDiscardConfirm"
      :title="t('git.confirmDiscardTitle')"
      :message="t('git.confirmDiscardDesc', { count: selectedFiles.size })"
      @confirm="executeDiscard"
      @cancel="showDiscardConfirm = false"
    />
  </div>
</template>

<style scoped>
.changes-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.changes-header {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.changes-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  margin-right: auto;
}

.changes-btn {
  padding: 3px 8px;
  border: 1px solid var(--border-glass);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all var(--transition);
}

.changes-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.changes-btn:disabled {
  opacity: 0.3;
  cursor: default;
}

.changes-btn.accent {
  color: var(--accent);
  border-color: var(--accent-muted);
}

.changes-btn.danger {
  color: var(--danger);
  border-color: var(--danger-muted);
}

.changes-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.changes-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.changes-section-label {
  padding: 6px 12px 2px;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
}

.changes-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: default;
  transition: background var(--transition);
}

.changes-file:hover {
  background: var(--bg-glass-hover);
}

.changes-file.selected {
  background: var(--accent-muted);
}

.changes-file.staged {
  opacity: 0.7;
}

.changes-check {
  font-size: 11px;
  color: var(--accent);
  width: 14px;
  flex-shrink: 0;
}

.changes-file-type {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 4px;
  border-radius: 3px;
  text-transform: uppercase;
  width: 16px;
  text-align: center;
  flex-shrink: 0;
}

.changes-file-type.untracked { background: var(--accent-muted); color: var(--accent); }
.changes-file-type.modified { background: rgba(21, 101, 192, 0.1); color: #1565c0; }
.changes-file-type.added { background: rgba(22, 101, 52, 0.1); color: #166534; }
.changes-file-type.deleted { background: rgba(185, 28, 28, 0.1); color: #b91c1c; }
.changes-file-type.renamed { background: rgba(94, 74, 208, 0.1); color: #5e4ad0; }

.changes-file-path {
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: Consolas, Monaco, monospace;
}
</style>
