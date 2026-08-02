<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import { useWorkflowEngine } from '@/composables/useWorkflowEngine'
import WorkflowCanvas from './WorkflowCanvas.vue'
import WorkflowToolbar from './WorkflowToolbar.vue'
import WorkflowLauncher from './WorkflowLauncher.vue'
import PropertyPanel from './PropertyPanel.vue'
import InspectPanel from './InspectPanel.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import type { WorkflowDefinition } from '@/types/workflow'
import type { WorkflowSummary } from '@/services/workflow'
import { fetchWorkflow, createWorkflow, updateWorkflow, deleteWorkflow, listWorkflows, exportWorkflowToFile } from '@/services/workflow'

const props = defineProps<{
  theme: 'dark' | 'light'
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const engine = useWorkflowEngine()

const showInspect = ref(false)
const runError = ref<string | null>(null)
const showLauncher = computed(() => workflowStore.showLauncher)
const workflowsList = ref<WorkflowSummary[]>([])
const listError = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const canvasRef = ref<InstanceType<typeof WorkflowCanvas> | null>(null)

// ── 切换/新建前的未保存改动确认 ──
const dirtyConfirmVisible = ref(false)
let pendingAction: (() => void | Promise<void>) | null = null

const workflowName = computed(() => workflowStore.workflow?.name ?? t('workflow.untitled'))
const isRunning = computed(() => engine.isRunning.value)
const canUndo = computed(() => workflowStore.canUndo)
const canRedo = computed(() => workflowStore.canRedo)

const pendingConfirmation = computed(() => {
  const entries = Object.entries(engine.pendingConfirmations.value)
  return entries.length > 0 ? entries[0] : null
})
const confirmationRequestId = computed(() => pendingConfirmation.value?.[0] ?? null)
const confirmationInfo = computed(() => pendingConfirmation.value?.[1] ?? null)
const confirmationVisible = computed(() => confirmationRequestId.value !== null)
const confirmationMessage = computed(() => {
  const info = confirmationInfo.value
  if (!info) return ''
  const argsText = info.toolCall.arguments
    ? JSON.stringify(info.toolCall.arguments, null, 2)
    : '{}'
  return t('workflow.confirmToolMessage', {
    nodeId: info.nodeId,
    tool: String(info.toolCall.name ?? ''),
    args: argsText,
  })
})

async function refreshWorkflowList() {
  try {
    workflowsList.value = await listWorkflows()
    listError.value = null
  } catch (e) {
    workflowsList.value = []
    listError.value = e instanceof Error ? e.message : String(e)
  }
}

// 当前工作流有未保存改动时，先弹确认框再执行会丢弃改动的动作（打开/新建/导入）
function guardDirty(action: () => void | Promise<void>) {
  if (workflowStore.isDirty) {
    pendingAction = action
    dirtyConfirmVisible.value = true
  } else {
    action()
  }
}

async function confirmDiscardChanges() {
  dirtyConfirmVisible.value = false
  const action = pendingAction
  pendingAction = null
  if (action) await action()
}

function cancelDiscardChanges() {
  dirtyConfirmVisible.value = false
  pendingAction = null
}

function handleCreateBlank() {
  guardDirty(() => {
    const now = Date.now()
    const def: WorkflowDefinition = {
      id: `wf-${now}`,
      name: t('workflow.untitled'),
      version: 1,
      nodes: [],
      edges: [],
      variables: [],
      executionConfig: { autoApproveWrites: false },
      createdAt: now,
      updatedAt: now,
    }
    workflowStore.setWorkflow(def)
    workflowStore.setShowLauncher(false)
  })
}

async function handleCreateNamed(name: string) {
  guardDirty(async () => {
    const now = Date.now()
    const def: WorkflowDefinition = {
      id: `wf-${now}`,
      name: name.trim() || t('workflow.untitled'),
      version: 1,
      nodes: [],
      edges: [],
      variables: [],
      executionConfig: { autoApproveWrites: false },
      createdAt: now,
      updatedAt: now,
    }
    try {
      runError.value = null
      const saved = await createWorkflow(def)
      workflowStore.setWorkflow(saved)
      workflowStore.markClean()
      workflowStore.setShowLauncher(false)
      await refreshWorkflowList()
    } catch (e) {
      runError.value = e instanceof Error ? e.message : String(e)
    }
  })
}

async function handleSave() {
  const def = workflowStore.workflow
  if (!def) return
  try {
    runError.value = null
    let saved: WorkflowDefinition
    try {
      saved = await updateWorkflow(def.id, def)
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      if (message.toLowerCase().includes('not found') || message.includes('不存在')) {
        saved = await createWorkflow(def)
      } else {
        throw e
      }
    }
    workflowStore.setWorkflow(saved)
    workflowStore.markClean()
    await refreshWorkflowList()
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e)
  }
}

async function handleSaveAs() {
  const def = workflowStore.workflow
  if (!def) return
  try {
    runError.value = null
    const now = Date.now()
    const copy: WorkflowDefinition = {
      ...def,
      id: `wf-${now}`,
      name: `${def.name || t('workflow.untitled')} (${t('workflow.copySuffix')})`,
      version: 1,
      createdAt: now,
      updatedAt: now,
    }
    const saved = await createWorkflow(copy)
    workflowStore.setWorkflow(saved)
    workflowStore.markClean()
    await refreshWorkflowList()
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e)
  }
}

async function handleLoad(id: string) {
  guardDirty(() => loadWorkflow(id))
}

async function loadWorkflow(id: string) {
  try {
    runError.value = null
    const def = await fetchWorkflow(id)
    workflowStore.setWorkflow(def)
    workflowStore.setShowLauncher(false)
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e)
  }
}

async function handleRun() {
  const def = workflowStore.workflow
  if (!def) return
  runError.value = null
  await handleSave()
  if (runError.value) {
    // 保存失败时中止运行，避免用旧持久化版本执行新画布内容
    return
  }
  const startNode = def.nodes.find((n) => n.type === 'start')
  const initialInput = String(startNode?.config.defaultValue ?? '')
  await engine.start(def.id, initialInput)
}

async function handleStop() {
  await engine.stop()
}

async function handleConfirmTool(approved: boolean) {
  const requestId = confirmationRequestId.value
  if (!requestId) return
  await engine.submitConfirmation(requestId, approved)
}

async function handleRename(name: string) {
  const def = workflowStore.workflow
  if (!def) return
  def.name = name
  workflowStore.setWorkflow({ ...def })
  await handleSave()
}

async function handleDelete(id: string) {
  try {
    runError.value = null
    await deleteWorkflow(id)
    await refreshWorkflowList()
    if (workflowStore.workflow?.id === id) {
      workflowStore.setWorkflow(null)
      workflowStore.setShowLauncher(true)
    }
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e)
  }
}

async function handleExport(id: string) {
  try {
    runError.value = null
    let def = workflowStore.workflow
    if (!def || def.id !== id) {
      def = await fetchWorkflow(id)
    }
    const defaultName = `${def.name || t('workflow.untitled')}.zaowu-workflow.json`

    if (window.pywebview?.api?.save_file_dialog) {
      const filePath = await window.pywebview.api.save_file_dialog(defaultName)
      if (!filePath) return
      await exportWorkflowToFile(id, filePath)
      return
    }

    const blob = new Blob([JSON.stringify(def, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = defaultName
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e)
  }
}

function triggerImport() {
  fileInput.value?.click()
}

async function handleImport(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  guardDirty(async () => {
    try {
      runError.value = null
      const text = await file.text()
      const imported = JSON.parse(text) as Partial<WorkflowDefinition>
      if (!Array.isArray(imported.nodes) || !imported.id || !imported.name) {
        throw new Error(t('workflow.importInvalid'))
      }
      const now = Date.now()
      const def: WorkflowDefinition = {
        ...imported,
        id: `wf-${now}`,
        name: `${imported.name || t('workflow.untitled')} (${t('workflow.importSuffix')})`,
        version: 1,
        createdAt: now,
        updatedAt: now,
      } as WorkflowDefinition
      const saved = await createWorkflow(def)
      workflowStore.setWorkflow(saved)
      workflowStore.setShowLauncher(false)
      await refreshWorkflowList()
    } catch (e) {
      runError.value = e instanceof Error ? e.message : String(e)
    } finally {
      if (fileInput.value) fileInput.value.value = ''
    }
  })
}

onMounted(() => {
  if (!workflowStore.workflow) {
    workflowStore.setShowLauncher(true)
  } else {
    workflowStore.setShowLauncher(false)
  }
  refreshWorkflowList()
})

// 运行结束后刷新列表：touch_run_metadata 在 wf_started 时更新了服务端 lastRunAt/runCount，
// 前端列表需重新拉取才能在 Launcher 中反映最新的「最近运行」。
watch(isRunning, (now, prev) => {
  if (prev && !now) {
    refreshWorkflowList()
  }
})

function handleOpenLauncher() {
  workflowStore.setShowLauncher(true)
  refreshWorkflowList()
}

function handleDeleteSelected() {
  canvasRef.value?.deleteSelectedItems()
}

function handleCopy() {
  canvasRef.value?.copySelectedItems()
}

function handlePaste() {
  canvasRef.value?.pasteItems()
}

function handleUndo() {
  workflowStore.undo()
}

function handleRedo() {
  workflowStore.redo()
}
</script>

<template>
  <div class="workflow-panel" :class="`theme-${props.theme}`">
    <WorkflowToolbar
      v-if="!showLauncher"
      :id="workflowStore.workflow?.id"
      :name="workflowName"
      :is-running="isRunning"
      :is-dirty="workflowStore.isDirty"
      :workflows="workflowsList"
      :can-undo="canUndo"
      :can-redo="canRedo"
      @create-blank="handleCreateBlank"
      @save="handleSave"
      @save-as="handleSaveAs"
      @open-launcher="handleOpenLauncher"
      @load="handleLoad"
      @delete="handleDelete"
      @rename="handleRename"
      @toggle-inspect="showInspect = !showInspect"
      @run="handleRun"
      @stop="handleStop"
      @export-workflow="handleExport"
      @import-workflow="triggerImport"
      @delete-selected="handleDeleteSelected"
      @copy="handleCopy"
      @paste="handlePaste"
      @undo="handleUndo"
      @redo="handleRedo"
    />
    <input
      ref="fileInput"
      type="file"
      accept=".json,.zaowu-workflow.json"
      class="hidden-file-input"
      @change="handleImport"
    />
    <div v-if="runError" class="error-banner">{{ runError }}</div>
    <WorkflowLauncher
      v-if="showLauncher"
      :workflows="workflowsList"
      :list-error="listError"
      :theme="props.theme"
      @create-named="handleCreateNamed"
      @import="triggerImport"
      @open="handleLoad"
      @delete="handleDelete"
    />
    <template v-else>
      <div class="workflow-body">
        <WorkflowCanvas ref="canvasRef" class="workflow-canvas-area" />
        <PropertyPanel class="workflow-property" />
      </div>
      <InspectPanel v-if="showInspect" class="workflow-inspect" />
      <ConfirmDialog
        :visible="confirmationVisible"
        :title="t('workflow.confirmToolTitle')"
        :message="confirmationMessage"
        @confirm="handleConfirmTool(true)"
        @cancel="handleConfirmTool(false)"
      />
    </template>
    <ConfirmDialog
      :visible="dirtyConfirmVisible"
      :title="t('workflow.unsavedChangesTitle')"
      :message="t('workflow.unsavedChangesMessage')"
      @confirm="confirmDiscardChanges"
      @cancel="cancelDiscardChanges"
    />
  </div>
</template>

<style scoped>
.workflow-panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: var(--bg-primary);
  color: var(--text-primary);
}

.workflow-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.workflow-canvas-area {
  flex: 1;
  min-width: 0;
}

.workflow-property {
  width: 260px;
  flex-shrink: 0;
  border-left: 1px solid var(--border-subtle);
}

.workflow-inspect {
  height: 220px;
  flex-shrink: 0;
  border-top: 1px solid var(--border-subtle);
}

.error-banner {
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
  font-size: 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.hidden-file-input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
  pointer-events: none;
}
</style>
