<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'
import ConfirmDialog from './ConfirmDialog.vue'
import GitStashDialog from './GitStashDialog.vue'

const { t } = useI18n()
const gitStore = useGitStore()

const batchMode = ref(false)
const selectedFiles = ref<Set<string>>(new Set())
const showDiscardConfirm = ref(false)
const showDiscardUntrackedConfirm = ref(false)
const showStashDialog = ref(false)

const untrackedFiles = computed(() => gitStore.untrackedChanges)
const stagedFiles = computed(() => gitStore.stagedChanges)
const unstagedFiles = computed(() => gitStore.unstagedChanges)
const conflictFiles = computed(() => gitStore.conflictChanges)
const hasChanges = computed(() => untrackedFiles.value.length > 0 || unstagedFiles.value.length > 0 || stagedFiles.value.length > 0 || conflictFiles.value.length > 0)

const allSelectable = computed(() => [...untrackedFiles.value, ...unstagedFiles.value].map(f => f.path))
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

watch(() => gitStore.selectedProject?.id, () => {
  batchMode.value = false
  selectedFiles.value.clear()
})

async function unstageSingle(path: string) {
  await gitStore.unstageFiles([path])
}

async function stageSelected() {
  const files = [...selectedFiles.value]
  if (files.length === 0) return
  await gitStore.stageFiles(files)
  exitBatchMode()
}

async function unstageSelected() {
  const files = [...selectedFiles.value]
  if (files.length === 0) return
  await gitStore.unstageFiles(files)
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

function confirmDiscardUntracked() {
  showDiscardUntrackedConfirm.value = true
}

async function executeDiscardUntracked() {
  showDiscardUntrackedConfirm.value = false
  const files = untrackedFiles.value.map(f => f.path)
  if (files.length > 0) {
    await gitStore.discardFiles(files, true)
  }
}

async function resolveOurs(path: string) {
  await gitStore.resolveAcceptOurs([path])
}

async function resolveTheirs(path: string) {
  await gitStore.resolveAcceptTheirs([path])
}
</script>

<template>
  <div class="changes-list">
    <div class="changes-header">
      <span class="changes-title">{{ t('git.changes') }}</span>
      <button
        v-if="!batchMode && hasChanges"
        class="changes-btn"
        :title="t('git.stash')"
        @click="showStashDialog = true"
      >
        {{ t('git.stash') }}
      </button>
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
        <div class="changes-section-label">
          {{ t('git.untrackedChanges') }} ({{ untrackedFiles.length }})
          <button
            v-if="!batchMode"
            class="changes-section-action"
            :title="t('git.discardAllUntracked')"
            @click="confirmDiscardUntracked"
          >
            {{ t('git.discardAllUntracked') }}
          </button>
        </div>
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

      <template v-if="unstagedFiles.length > 0">
        <div class="changes-section-label">{{ t('git.unstagedChanges') }} ({{ unstagedFiles.length }})</div>
        <div
          v-for="f in unstagedFiles"
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
          @click="batchMode ? toggleFile(f.path) : unstageSingle(f.path)"
        >
          <span v-if="batchMode" class="changes-check">{{ selectedFiles.has(f.path) ? '✓' : '○' }}</span>
          <span class="changes-file-type" :class="f.type">{{ (f.type?.[0] || '?').toUpperCase() }}</span>
          <span class="changes-file-path">{{ f.path }}</span>
        </div>
      </template>

      <template v-if="conflictFiles.length > 0">
        <div class="changes-section-label conflict">{{ t('git.conflictChanges') }} ({{ conflictFiles.length }})</div>
        <div
          v-for="f in conflictFiles"
          :key="f.path"
          class="changes-file conflict"
        >
          <span class="changes-file-type conflict">C</span>
          <span class="changes-file-path">{{ f.path }}</span>
          <span v-if="!batchMode" class="conflict-actions">
            <button class="conflict-btn" :title="t('git.acceptOurs')" @click.stop="resolveOurs(f.path)">{{ t('git.ours') }}</button>
            <button class="conflict-btn" :title="t('git.acceptTheirs')" @click.stop="resolveTheirs(f.path)">{{ t('git.theirs') }}</button>
          </span>
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
    <ConfirmDialog
      :visible="showDiscardUntrackedConfirm"
      :title="t('git.confirmDiscardTitle')"
      :message="t('git.confirmDiscardUntracked')"
      @confirm="executeDiscardUntracked"
      @cancel="showDiscardUntrackedConfirm = false"
    />
    <GitStashDialog
      v-if="showStashDialog"
      @close="showStashDialog = false"
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px 2px;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
}

.changes-section-action {
  font-size: 10px;
  font-weight: 400;
  text-transform: none;
  padding: 1px 6px;
  border: 1px solid var(--danger-muted, rgba(185, 28, 28, 0.2));
  border-radius: 3px;
  background: transparent;
  color: var(--danger);
  cursor: pointer;
  transition: all var(--transition);
}

.changes-section-action:hover {
  background: var(--danger-muted, rgba(185, 28, 28, 0.1));
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
.changes-section-label.conflict { color: #b91c1c; }
.changes-file.conflict { background: rgba(185, 28, 28, 0.05); }
.changes-file-type.conflict { background: rgba(185, 28, 28, 0.15); color: #b91c1c; }

.changes-file-path {
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: Consolas, Monaco, monospace;
}

.conflict-actions {
  display: flex;
  gap: 4px;
  margin-left: auto;
}

.conflict-btn {
  font-size: 10px;
  padding: 1px 6px;
  border: 1px solid var(--border-glass);
  border-radius: 3px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.conflict-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}
</style>
