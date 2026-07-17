<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus, CheckSquare, ChevronDown, ChevronRight, Archive, Upload, Trash2, X } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useProjectsStore } from '@/stores/projects'
import ProjectCard from './ProjectCard.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import LoadingOverlay from './LoadingOverlay.vue'
import ErrorToast from './ErrorToast.vue'

const { t } = useI18n()
const store = useProjectsStore()

const showArchived = ref(false)
const showConfirm = ref(false)
const confirmAction = ref<'archive' | 'unload' | 'delete'>('archive')
const confirmCount = ref(0)
const loading = ref(false)
const loadingProgress = ref('')
const errorMsg = ref('')

onMounted(() => {
  store.fetchProjects()
})

async function addProject() {
  if (!window.pywebview) return
  const path = await window.pywebview.api.select_folder()
  if (!path) return
  const result = await store.addProject(path)
  if (!result.ok) {
    showError(result.error || 'operationFailed')
  }
}

async function handleSingleAction(action: 'archive' | 'unload' | 'delete', projectId: string) {
  let ok = false
  if (action === 'archive') {
    ok = await store.archiveProject(projectId)
  } else if (action === 'unload') {
    ok = await store.unloadProject(projectId)
  } else if (action === 'delete') {
    ok = await store.deleteProject(projectId)
  }
  if (!ok) {
    showError(t('explorer.operationFailed'))
  }
}

function handleUnarchive(projectId: string) {
  store.unarchiveProject(projectId)
}

function startBatchAction(action: 'archive' | 'unload' | 'delete') {
  confirmAction.value = action
  confirmCount.value = store.batchSelected.size
  showConfirm.value = true
}

async function executeBatchAction() {
  showConfirm.value = false
  loading.value = true
  const total = store.batchSelected.size
  let current = 0

  const updateProgress = () => {
    current++
    loadingProgress.value = t('explorer.processing', { current, total })
  }

  try {
    const startTime = Date.now()
    let result
    if (confirmAction.value === 'archive') {
      result = await store.batchArchive()
    } else if (confirmAction.value === 'unload') {
      result = await store.batchUnload()
    } else {
      result = await store.batchDelete()
    }

    const elapsed = Date.now() - startTime
    if (elapsed < 250) {
      await new Promise(r => setTimeout(r, 250 - elapsed))
    }

    if (!result.ok) {
      showError(t('explorer.operationFailed'))
    }
  } finally {
    loading.value = false
    loadingProgress.value = ''
    store.exitBatchMode()
  }
}

function showError(msg: string) {
  errorMsg.value = msg
}
</script>

<template>
  <div class="explorer-panel">
    <div class="explorer-toolbar">
      <button class="toolbar-btn" :title="t('explorer.addProject')" @click="addProject">
        <Plus :size="16" />
      </button>
      <button
        class="toolbar-btn"
        :class="{ active: store.batchMode }"
        :title="t('explorer.batchMode')"
        @click="store.batchMode ? store.exitBatchMode() : store.enterBatchMode()"
      >
        <CheckSquare :size="16" />
      </button>
    </div>

    <div class="explorer-list">
      <div v-if="store.activeProjects.length === 0 && store.archivedProjects.length === 0" class="empty-state">
        {{ t('explorer.noProjects') }}
      </div>

      <ProjectCard
        v-for="project in store.activeProjects"
        :key="project.id"
        :project="project"
        :batch-mode="store.batchMode"
        :selected="store.batchSelected.has(project.id)"
        @archive="handleSingleAction('archive', $event)"
        @unarchive="handleUnarchive"
        @unload="handleSingleAction('unload', $event)"
        @delete="handleSingleAction('delete', $event)"
      />

      <div v-if="store.archivedProjects.length > 0" class="archived-section">
        <div class="archived-header" @click="showArchived = !showArchived">
          <span class="archived-arrow" :class="{ expanded: showArchived }">
            <ChevronRight :size="14" />
          </span>
          <span class="archived-title">{{ t('explorer.archivedProjects') }}</span>
          <span class="archived-count">{{ store.archivedProjects.length }}</span>
        </div>
        <div v-if="showArchived" class="archived-list">
          <ProjectCard
            v-for="project in store.archivedProjects"
            :key="project.id"
            :project="project"
            :batch-mode="false"
            :selected="false"
            @archive="handleSingleAction('archive', $event)"
            @unarchive="handleUnarchive"
            @unload="handleSingleAction('unload', $event)"
            @delete="handleSingleAction('delete', $event)"
          />
        </div>
      </div>
    </div>

    <div v-if="store.batchMode && store.batchSelected.size > 0" class="batch-footer">
      <button class="batch-btn" :title="t('explorer.batchArchive')" @click="startBatchAction('archive')">
        <Archive :size="16" />
        <span>{{ t('explorer.batchArchiveShort') }}</span>
      </button>
      <button class="batch-btn" :title="t('explorer.batchUnload')" @click="startBatchAction('unload')">
        <Upload :size="16" />
        <span>{{ t('explorer.batchUnloadShort') }}</span>
      </button>
      <button class="batch-btn danger" :title="t('explorer.batchDelete')" @click="startBatchAction('delete')">
        <Trash2 :size="16" />
        <span>{{ t('explorer.batchDeleteShort') }}</span>
      </button>
      <button class="batch-btn" :title="t('explorer.cancel')" @click="store.exitBatchMode()">
        <X :size="16" />
        <span>{{ t('explorer.cancel') }}</span>
      </button>
    </div>

    <ConfirmDialog
      :visible="showConfirm"
      :title="t('explorer.confirmTitle')"
      :message="t('explorer.confirm' + confirmAction.charAt(0).toUpperCase() + confirmAction.slice(1), { count: confirmCount })"
      @confirm="executeBatchAction"
      @cancel="showConfirm = false"
    />

    <LoadingOverlay :visible="loading" :progress="loadingProgress" />

    <Teleport to="body">
      <ErrorToast
        v-if="errorMsg"
        :message="errorMsg"
        type="error"
        @close="errorMsg = ''"
      />
    </Teleport>
  </div>
</template>

<style scoped>
.explorer-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.explorer-toolbar {
  display: flex;
  gap: 4px;
  padding: 8px;
  border-bottom: 1px solid var(--border-subtle);
}

.toolbar-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.toolbar-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

.toolbar-btn.active {
  background: var(--accent-muted);
  color: var(--accent);
}

.explorer-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.empty-state {
  text-align: center;
  padding: 24px;
  font-size: 13px;
  color: var(--text-tertiary);
}

.archived-section {
  margin-top: 8px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 8px;
}

.archived-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
}

.archived-header:hover {
  background: var(--bg-glass-hover);
}

.archived-arrow {
  flex-shrink: 0;
  color: var(--text-tertiary);
  transition: transform 0.15s;
}

.archived-arrow.expanded {
  transform: rotate(90deg);
}

.archived-title {
  font-size: 12px;
  color: var(--text-secondary);
  flex: 1;
}

.archived-count {
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 1px 6px;
  border-radius: 4px;
}

.archived-list {
  margin-top: 4px;
}

.batch-footer {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
}

.batch-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-height: 52px;
  padding: 8px;
  border: none;
  border-radius: 8px;
  font-size: 11px;
  cursor: pointer;
  background: var(--bg-glass);
  color: var(--text-primary);
  transition: all 0.15s;
}

.batch-btn:hover {
  background: var(--bg-glass-hover);
}

.batch-btn.danger {
  color: var(--danger);
}

.batch-btn.danger:hover {
  background: var(--danger-muted);
}
</style>
