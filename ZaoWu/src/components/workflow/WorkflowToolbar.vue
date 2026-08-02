<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { Play, Square, Save, Download, Upload, Plus, Activity, FolderOpen, Trash2, Copy, ClipboardPaste, Scissors, Undo2, Redo2 } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { WorkflowSummary } from '@/services/workflow'

const props = defineProps<{
  id?: string
  name: string
  isRunning: boolean
  isDirty: boolean
  workflows?: WorkflowSummary[]
  canUndo?: boolean
  canRedo?: boolean
}>()

const emit = defineEmits<{
  createBlank: []
  save: []
  saveAs: []
  exportWorkflow: [id: string]
  importWorkflow: []
  toggleInspect: []
  run: []
  stop: []
  openLauncher: []
  load: [id: string]
  delete: [id: string]
  rename: [name: string]
  copy: []
  paste: []
  deleteSelected: []
  undo: []
  redo: []
}>()

const { t } = useI18n()
const renameDialogVisible = ref(false)
const renameDialogInput = ref<HTMLInputElement | null>(null)
const renameDialogValue = ref('')
const exportDialogVisible = ref(false)
const selectedExportId = ref<string>('')
const deleteDialogVisible = ref(false)
const selectedDeleteId = ref<string>('')

function startRename() {
  renameDialogVisible.value = true
  renameDialogValue.value = props.name
  nextTick(() => {
    renameDialogInput.value?.focus()
    renameDialogInput.value?.select()
  })
}

function confirmRename() {
  const trimmed = renameDialogValue.value.trim()
  if (trimmed && trimmed !== props.name) {
    emit('rename', trimmed)
  }
  renameDialogVisible.value = false
}

function cancelRename() {
  renameDialogVisible.value = false
}

function openExportDialog() {
  const list = props.workflows ?? []
  if (list.length) {
    selectedExportId.value = props.id && list.some((w) => w.id === props.id)
      ? props.id
      : list[0]!.id
  } else {
    selectedExportId.value = props.id || ''
  }
  exportDialogVisible.value = true
}

function confirmExport() {
  if (selectedExportId.value) {
    emit('exportWorkflow', selectedExportId.value)
  }
  exportDialogVisible.value = false
}

function cancelExport() {
  exportDialogVisible.value = false
}

function openDeleteDialog() {
  const list = props.workflows ?? []
  if (list.length) {
    selectedDeleteId.value = props.id && list.some((w) => w.id === props.id)
      ? props.id
      : list[0]!.id
  } else {
    selectedDeleteId.value = props.id || ''
  }
  deleteDialogVisible.value = true
}

function confirmDelete() {
  if (selectedDeleteId.value) {
    emit('delete', selectedDeleteId.value)
  }
  deleteDialogVisible.value = false
}

function cancelDelete() {
  deleteDialogVisible.value = false
}
</script>

<template>
  <header class="workflow-toolbar">
    <div class="toolbar-left">
      <div class="workflow-name-wrapper">
        <span class="workflow-name" @click="startRename">{{ props.name }}</span>
        <span v-if="props.isDirty" class="dirty-dot" title="未保存的修改" />
      </div>
      <button class="tool-btn" :title="t('workflow.new')" @click="emit('createBlank')">
        <Plus :size="14" />
        <span>{{ t('workflow.new') }}</span>
      </button>
      <button
        class="tool-btn"
        :title="t('workflow.delete')"
        :disabled="!props.workflows?.length && !props.id"
        @click="openDeleteDialog"
      >
        <Trash2 :size="14" />
        <span>{{ t('workflow.delete') }}</span>
      </button>
      <button class="tool-btn" :title="t('workflow.open')" @click="emit('openLauncher')">
        <FolderOpen :size="14" />
        <span>{{ t('workflow.open') }}</span>
      </button>

      <div class="toolbar-divider" />

      <button class="tool-btn" :title="t('workflow.copy') + ' (Ctrl+C)'" @click="emit('copy')">
        <Copy :size="14" />
        <span>{{ t('workflow.copy') }}</span>
      </button>
      <button class="tool-btn" :title="t('workflow.paste') + ' (Ctrl+V)'" @click="emit('paste')">
        <ClipboardPaste :size="14" />
        <span>{{ t('workflow.paste') }}</span>
      </button>
      <button
        class="tool-btn"
        :title="t('workflow.deleteSelected') + ' (Delete)'"
        @click="emit('deleteSelected')"
      >
        <Scissors :size="14" />
        <span>{{ t('workflow.deleteSelected') }}</span>
      </button>

      <div class="toolbar-divider" />

      <button
        class="tool-btn"
        :title="t('workflow.undo') + ' (Ctrl+Z)'"
        :disabled="!props.canUndo"
        @click="emit('undo')"
      >
        <Undo2 :size="14" />
        <span>{{ t('workflow.undo') }}</span>
      </button>
      <button
        class="tool-btn"
        :title="t('workflow.redo') + ' (Ctrl+Shift+Z)'"
        :disabled="!props.canRedo"
        @click="emit('redo')"
      >
        <Redo2 :size="14" />
        <span>{{ t('workflow.redo') }}</span>
      </button>
    </div>

    <div class="toolbar-right">
      <button
        v-if="!props.isRunning"
        class="tool-btn"
        :title="t('workflow.run')"
        @click="emit('run')"
      >
        <Play :size="14" />
        <span>{{ t('workflow.run') }}</span>
      </button>
      <button
        v-else
        class="tool-btn"
        :title="t('workflow.stop')"
        @click="emit('stop')"
      >
        <Square :size="14" />
        <span>{{ t('workflow.stop') }}</span>
      </button>

      <button class="tool-btn" :title="t('workflow.save')" @click="emit('save')">
        <Save :size="14" />
        <span>{{ t('workflow.save') }}</span>
      </button>

      <button class="tool-btn" :title="t('workflow.saveAs')" @click="emit('saveAs')">
        <Copy :size="14" />
        <span>{{ t('workflow.saveAs') }}</span>
      </button>

      <button class="tool-btn" :title="t('workflow.import')" @click="emit('importWorkflow')">
        <Download :size="14" />
        <span>{{ t('workflow.import') }}</span>
      </button>
      <button class="tool-btn" :title="t('workflow.export')" @click="openExportDialog">
        <Upload :size="14" />
        <span>{{ t('workflow.export') }}</span>
      </button>
      <button class="tool-btn" :title="t('workflow.inspect')" @click="emit('toggleInspect')">
        <Activity :size="14" />
        <span>{{ t('workflow.inspect') }}</span>
      </button>
    </div>
  </header>

  <div
    v-if="renameDialogVisible"
    class="rename-dialog-overlay"
    @click="cancelRename"
  >
    <div class="rename-dialog" @click.stop>
      <div class="rename-dialog-title">{{ t('workflow.rename') }}</div>
      <input
        ref="renameDialogInput"
        v-model="renameDialogValue"
        class="rename-dialog-input"
        @keydown.enter="confirmRename"
        @keydown.esc="cancelRename"
      />
      <div class="rename-dialog-actions">
        <button class="tool-btn" @click="cancelRename">
          {{ t('common.cancel') }}
        </button>
        <button class="tool-btn primary" @click="confirmRename">
          {{ t('common.confirm') }}
        </button>
      </div>
    </div>
  </div>

  <div
    v-if="exportDialogVisible"
    class="export-dialog-overlay"
    @click="cancelExport"
  >
    <div class="export-dialog" @click.stop>
      <div class="export-dialog-title">{{ t('workflow.exportTitle') }}</div>
      <select
        v-if="props.workflows?.length"
        v-model="selectedExportId"
        class="export-dialog-select"
      >
        <option
          v-for="w in props.workflows"
          :key="w.id"
          :value="w.id"
        >
          {{ w.name }} (v{{ w.version }})
        </option>
      </select>
      <div v-else class="export-dialog-empty">
        {{ t('workflow.noExportableWorkflows') }}
      </div>
      <div class="export-dialog-actions">
        <button class="tool-btn" @click="cancelExport">
          {{ t('common.cancel') }}
        </button>
        <button
          class="tool-btn primary"
          :disabled="!selectedExportId"
          @click="confirmExport"
        >
          {{ t('workflow.export') }}
        </button>
      </div>
    </div>
  </div>

  <div
    v-if="deleteDialogVisible"
    class="delete-dialog-overlay"
    @click="cancelDelete"
  >
    <div class="delete-dialog" @click.stop>
      <div class="delete-dialog-title">{{ t('workflow.deleteTitle') }}</div>
      <select
        v-if="props.workflows?.length"
        v-model="selectedDeleteId"
        class="delete-dialog-select"
      >
        <option
          v-for="w in props.workflows"
          :key="w.id"
          :value="w.id"
        >
          {{ w.name }} (v{{ w.version }})
        </option>
      </select>
      <div v-else class="delete-dialog-empty">
        {{ t('workflow.noDeletableWorkflows') }}
      </div>
      <div class="delete-dialog-actions">
        <button class="tool-btn" @click="cancelDelete">
          {{ t('common.cancel') }}
        </button>
        <button
          class="tool-btn"
          :disabled="!selectedDeleteId"
          @click="confirmDelete"
        >
          {{ t('workflow.delete') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workflow-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 44px;
  padding: 0 12px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-subtle);
}

.toolbar-left,
.toolbar-center,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-left {
  min-width: 0;
  flex-shrink: 1;
}

.toolbar-divider {
  width: 1px;
  height: 20px;
  background: var(--border-subtle);
  flex-shrink: 0;
}

.workflow-name-wrapper {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  max-width: 200px;
  overflow: hidden;
}

.dirty-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #f59e0b;
  flex-shrink: 0;
  box-shadow: 0 0 4px rgba(245, 158, 11, 0.5);
}

.workflow-name {
  display: block;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  transition: background 0.15s;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-name:hover {
  background: var(--bg-hover);
}

.rename-dialog-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
  z-index: 200;
}

.rename-dialog {
  width: 360px;
  padding: 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
}

.rename-dialog-title {
  margin-bottom: 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.rename-dialog-input {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  outline: none;
  box-sizing: border-box;
}

.rename-dialog-input:focus {
  border-color: var(--accent);
}

.rename-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.export-dialog-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
  z-index: 200;
}

.export-dialog {
  width: 380px;
  max-height: 480px;
  display: flex;
  flex-direction: column;
  padding: 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
}

.export-dialog-title {
  margin-bottom: 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.export-dialog-select {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  outline: none;
  box-sizing: border-box;
}

.export-dialog-select:focus {
  border-color: var(--accent);
}

.export-dialog-empty {
  min-height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  padding: 12px;
  font-size: 13px;
  color: var(--text-tertiary);
  background: var(--bg-primary);
  border: 1px dashed var(--border-subtle);
  border-radius: 6px;
}

.export-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.delete-dialog-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
  z-index: 200;
}

.delete-dialog {
  width: 380px;
  max-height: 480px;
  display: flex;
  flex-direction: column;
  padding: 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
}

.delete-dialog-title {
  margin-bottom: 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.delete-dialog-select {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  outline: none;
  box-sizing: border-box;
}

.delete-dialog-select:focus {
  border-color: var(--accent);
}

.delete-dialog-empty {
  min-height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  padding: 12px;
  font-size: 13px;
  color: var(--text-tertiary);
  background: var(--bg-primary);
  border: 1px dashed var(--border-subtle);
  border-radius: 6px;
}

.delete-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.15s;
}

.tool-btn:hover:not(:disabled) {
  background: var(--bg-hover);
}

.tool-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tool-btn.primary {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

@media (max-width: 1100px) {
  .tool-btn span {
    display: none;
  }

  .tool-btn {
    padding: 6px;
  }
}
</style>
