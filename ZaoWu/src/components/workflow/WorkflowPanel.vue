<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import { useWorkflowEngine } from '@/composables/useWorkflowEngine'
import WorkflowCanvas from './WorkflowCanvas.vue'
import WorkflowToolbar from './WorkflowToolbar.vue'
import PropertyPanel from './PropertyPanel.vue'
import InspectPanel from './InspectPanel.vue'
import type { WorkflowDefinition } from '@/types/workflow'
import { fetchWorkflow, createWorkflow, updateWorkflow } from '@/services/workflow'

const props = defineProps<{
  theme: 'dark' | 'light'
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const engine = useWorkflowEngine()

const showInspect = ref(false)
const runError = ref<string | null>(null)

const workflowName = computed(() => workflowStore.workflow?.name ?? t('workflow.untitled'))
const isRunning = computed(() => engine.isRunning.value)

function handleCreateBlank() {
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
}

async function handleSave() {
  const def = workflowStore.workflow
  if (!def) return
  try {
    runError.value = null
    if (def.version <= 1 && def.nodes.length === 0) {
      const saved = await createWorkflow(def)
      workflowStore.setWorkflow(saved)
    } else {
      const saved = await updateWorkflow(def.id, def)
      workflowStore.setWorkflow(saved)
    }
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e)
  }
}

async function handleLoad(id: string) {
  try {
    runError.value = null
    const def = await fetchWorkflow(id)
    workflowStore.setWorkflow(def)
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e)
  }
}

async function handleRun() {
  const def = workflowStore.workflow
  if (!def) return
  runError.value = null
  const startNode = def.nodes.find((n) => n.type === 'start')
  const initialInput = String(startNode?.config.defaultValue ?? '')
  await engine.start(def.id, initialInput)
}

async function handleStop() {
  await engine.stop()
}

onMounted(() => {
  if (!workflowStore.workflow) {
    handleCreateBlank()
  }
})
</script>

<template>
  <div class="workflow-panel" :class="`theme-${props.theme}`">
    <WorkflowToolbar
      :name="workflowName"
      :is-running="isRunning"
      @create-blank="handleCreateBlank"
      @save="handleSave"
      @toggle-inspect="showInspect = !showInspect"
      @run="handleRun"
      @stop="handleStop"
    />
    <div v-if="runError" class="error-banner">{{ runError }}</div>
    <div class="workflow-body">
      <WorkflowCanvas class="workflow-canvas-area" />
      <PropertyPanel class="workflow-property" />
    </div>
    <InspectPanel v-if="showInspect" class="workflow-inspect" />
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
</style>
