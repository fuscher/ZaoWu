<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import {
  Plus,
  Upload,
  Search,
  Clock,
  FolderOpen,
  Trash2,
  FileText,
  X,
} from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { WorkflowSummary } from '@/services/workflow'

const props = defineProps<{
  workflows: WorkflowSummary[]
  theme: 'dark' | 'light'
  listError?: string | null
}>()

const emit = defineEmits<{
  createNamed: [name: string]
  import: []
  open: [id: string]
  delete: [id: string]
}>()

const { t } = useI18n()
const search = ref('')
const deleteTarget = ref<WorkflowSummary | null>(null)
const createDialogVisible = ref(false)
const createDialogValue = ref('')
const createDialogInput = ref<HTMLInputElement | null>(null)

// 按最近运行/更新时间倒序，作为「最近打开」与全量列表的统一排序基准
const sortedWorkflows = computed(() => {
  return [...props.workflows].sort((a, b) => {
    const ta = b.lastRunAt ?? b.updatedAt ?? 0
    const tb = a.lastRunAt ?? a.updatedAt ?? 0
    return ta - tb
  })
})

// 「最近打开」固定取最近 6 个，不受搜索框过滤影响
const recentWorkflows = computed(() => sortedWorkflows.value.slice(0, 6))

const filteredWorkflows = computed(() => {
  const term = search.value.trim().toLowerCase()
  if (!term) return sortedWorkflows.value
  return sortedWorkflows.value.filter((w) => w.name.toLowerCase().includes(term))
})

const hasWorkflows = computed(() => props.workflows.length > 0)
const canCreate = computed(() => createDialogValue.value.trim().length > 0)

function formatTime(timestamp?: number): string {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  const now = new Date()
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  if (isToday) {
    return date.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    })
  }
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function confirmDelete(w: WorkflowSummary) {
  deleteTarget.value = w
}

function cancelDelete() {
  deleteTarget.value = null
}

function doDelete() {
  if (deleteTarget.value) {
    emit('delete', deleteTarget.value.id)
    deleteTarget.value = null
  }
}

function openCreateDialog() {
  createDialogVisible.value = true
  createDialogValue.value = t('workflow.untitled')
  nextTick(() => {
    createDialogInput.value?.focus()
    createDialogInput.value?.select()
  })
}

function confirmCreate() {
  const trimmed = createDialogValue.value.trim()
  if (!trimmed) return
  emit('createNamed', trimmed)
  createDialogVisible.value = false
}

function cancelCreate() {
  createDialogVisible.value = false
}
</script>

<template>
  <div class="workflow-launcher" :class="`theme-${props.theme}`">
    <div class="launcher-header">
      <div class="launcher-title">
        <FileText :size="22" />
        <span>{{ t('workflow.launcherTitle') }}</span>
      </div>
      <div class="launcher-actions">
        <button class="launcher-btn primary" @click="openCreateDialog">
          <Plus :size="14" />
          <span>{{ t('workflow.new') }}</span>
        </button>
        <button class="launcher-btn" @click="emit('import')">
          <Upload :size="14" />
          <span>{{ t('workflow.import') }}</span>
        </button>
      </div>
    </div>

    <div class="launcher-body">
      <div v-if="props.listError" class="launcher-empty">
        <FolderOpen :size="48" />
        <div class="launcher-empty-title">{{ t('workflow.listLoadErrorTitle') }}</div>
        <div class="launcher-empty-desc">{{ props.listError }}</div>
      </div>
      <div v-else-if="!hasWorkflows" class="launcher-empty">
        <FolderOpen :size="48" />
        <div class="launcher-empty-title">{{ t('workflow.launcherEmptyTitle') }}</div>
        <div class="launcher-empty-desc">{{ t('workflow.launcherEmptyDesc') }}</div>
      </div>

      <template v-else>
        <section class="launcher-section">
          <div class="section-title">
            <Clock :size="14" />
            <span>{{ t('workflow.recentWorkflows') }}</span>
          </div>
          <div class="recent-grid">
            <div
              v-for="w in recentWorkflows"
              :key="w.id"
              class="recent-card"
              @click="emit('open', w.id)"
            >
              <div class="recent-card-name">{{ w.name }}</div>
              <div class="recent-card-meta">
                <span>v{{ w.version }}</span>
                <span>{{ formatTime(w.lastRunAt ?? w.updatedAt) }}</span>
              </div>
            </div>
          </div>
        </section>

        <section class="launcher-section">
          <div class="section-header">
            <div class="section-title">
              <FolderOpen :size="14" />
              <span>{{ t('workflow.allWorkflows') }}</span>
            </div>
            <div class="search-box">
              <Search :size="14" />
              <input
                v-model="search"
                type="text"
                :placeholder="t('workflow.searchWorkflows')"
              />
              <button v-if="search" class="search-clear" @click="search = ''">
                <X :size="12" />
              </button>
            </div>
          </div>

          <div class="workflow-list">
            <div class="workflow-list-header">
              <span class="col-name">{{ t('workflow.name') }}</span>
              <span class="col-time">{{ t('workflow.lastRunAt') }}</span>
              <span class="col-version">{{ t('workflow.version') }}</span>
              <span class="col-action">{{ t('workflow.action') }}</span>
            </div>
            <div
              v-for="w in filteredWorkflows"
              :key="w.id"
              class="workflow-list-item"
            >
              <span class="col-name" @click="emit('open', w.id)">{{ w.name }}</span>
              <span class="col-time">{{ formatTime(w.lastRunAt ?? w.updatedAt) }}</span>
              <span class="col-version">v{{ w.version }}</span>
              <span class="col-action">
                <button class="icon-btn" :title="t('workflow.open')" @click="emit('open', w.id)">
                  <FolderOpen :size="14" />
                </button>
                <button class="icon-btn danger" :title="t('workflow.delete')" @click="confirmDelete(w)">
                  <Trash2 :size="14" />
                </button>
              </span>
            </div>
            <div v-if="!filteredWorkflows.length" class="workflow-list-empty">
              {{ t('workflow.noWorkflowsMatch') }}
            </div>
          </div>
        </section>
      </template>
    </div>

    <div
      v-if="deleteTarget"
      class="delete-dialog-overlay"
      @click="cancelDelete"
    >
      <div class="delete-dialog" @click.stop>
        <div class="delete-dialog-title">{{ t('workflow.deleteConfirmTitle') }}</div>
        <div class="delete-dialog-message">
          {{ t('workflow.deleteConfirmMessage', { name: deleteTarget.name }) }}
        </div>
        <div class="delete-dialog-actions">
          <button class="launcher-btn" @click="cancelDelete">
            {{ t('common.cancel') }}
          </button>
          <button class="launcher-btn danger" @click="doDelete">
            {{ t('workflow.delete') }}
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="createDialogVisible"
      class="create-dialog-overlay"
      @click="cancelCreate"
    >
      <div class="create-dialog" @click.stop>
        <div class="create-dialog-title">{{ t('workflow.createTitle') }}</div>
        <input
          ref="createDialogInput"
          v-model="createDialogValue"
          type="text"
          class="create-dialog-input"
          :placeholder="t('workflow.createNamePlaceholder')"
          @keydown.enter="confirmCreate"
          @keydown.esc="cancelCreate"
        />
        <div class="create-dialog-actions">
          <button class="launcher-btn" @click="cancelCreate">
            {{ t('common.cancel') }}
          </button>
          <button class="launcher-btn primary" :disabled="!canCreate" @click="confirmCreate">
            {{ t('common.create') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workflow-launcher {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: var(--bg-primary);
  color: var(--text-primary);
  overflow: hidden;
}

.launcher-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 28px;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.launcher-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.launcher-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.launcher-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s;
}

.launcher-btn:hover {
  background: var(--bg-hover);
}

.launcher-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.launcher-btn.primary {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.launcher-btn.primary:hover {
  opacity: 0.9;
}

.launcher-btn.danger {
  color: #ef4444;
  border-color: rgba(239, 68, 68, 0.3);
}

.launcher-btn.danger:hover {
  background: rgba(239, 68, 68, 0.1);
}

.launcher-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px 28px;
}

.launcher-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 16px;
  color: var(--text-tertiary);
}

.launcher-empty-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.launcher-empty-desc {
  font-size: 13px;
  text-align: center;
  max-width: 360px;
}

.launcher-section {
  margin-bottom: 40px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
  gap: 16px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.section-header .section-title {
  margin-bottom: 0;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
  width: 240px;
  height: 32px;
  padding: 0 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
}

.search-box input {
  flex: 1;
  min-width: 0;
  margin-left: 8px;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
}

.search-box input::placeholder {
  color: var(--text-tertiary);
}

.search-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2px;
  margin-left: 4px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 50%;
}

.search-clear:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.recent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.recent-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.recent-card:hover {
  background: var(--bg-hover);
  border-color: var(--accent);
}

.recent-card-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-tertiary);
}

.workflow-list {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  overflow: hidden;
}

.workflow-list-header,
.workflow-list-item {
  display: grid;
  grid-template-columns: 1fr 140px 80px 90px;
  align-items: center;
  padding: 10px 16px;
  font-size: 13px;
  gap: 12px;
}

.workflow-list-header {
  background: var(--bg-tertiary);
  color: var(--text-tertiary);
  font-weight: 500;
  border-bottom: 1px solid var(--border-subtle);
}

.workflow-list-item {
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-subtle);
}

.workflow-list-item:last-child {
  border-bottom: none;
}

.workflow-list-item:hover {
  background: var(--bg-hover);
}

.col-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  color: var(--text-primary);
}

.col-name:hover {
  color: var(--accent);
}

.col-time,
.col-version {
  color: var(--text-secondary);
}

.col-action {
  display: flex;
  align-items: center;
  gap: 6px;
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 4px;
  cursor: pointer;
}

.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.icon-btn.danger:hover {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.workflow-list-empty {
  padding: 32px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
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
  width: 360px;
  padding: 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
}

.delete-dialog-title {
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.delete-dialog-message {
  margin-bottom: 18px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.delete-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.create-dialog-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
  z-index: 200;
}

.create-dialog {
  width: 360px;
  padding: 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
}

.create-dialog-title {
  margin-bottom: 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.create-dialog-input {
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

.create-dialog-input:focus {
  border-color: var(--accent);
}

.create-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 800px) {
  .workflow-list-header,
  .workflow-list-item {
    grid-template-columns: 1fr 80px 70px;
  }

  .col-time {
    display: none;
  }

  .launcher-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 14px;
  }

  .search-box {
    width: 100%;
  }
}
</style>
