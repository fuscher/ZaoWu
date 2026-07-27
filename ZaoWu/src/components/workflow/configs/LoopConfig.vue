<script setup lang="ts">
import { computed } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import type { WorkflowNode, LoopConfig as LoopConfigType } from '@/types/workflow'

const props = defineProps<{
  node: WorkflowNode
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()

const cfg = computed<LoopConfigType>({
  get: () =>
    (props.node.config.loopConfig as LoopConfigType) ?? {
      mode: 'canvas',
      maxIterations: 10,
      bodyNodeIds: [],
      bodyEdges: [],
    },
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { loopConfig: v }),
})

function update(patch: Partial<LoopConfigType>) {
  cfg.value = { ...cfg.value, ...patch }
}
</script>

<template>
  <div class="config-form">
    <label class="field-label">{{ t('workflow.config.maxIterations') }}</label>
    <input
      :value="cfg.maxIterations"
      class="field-input"
      type="number"
      min="1"
      @input="update({ maxIterations: Number(($event.target as HTMLInputElement).value) })"
    />

    <p class="hint">{{ t('workflow.config.loopCanvasHint') }}</p>
  </div>
</template>

<style scoped>
.config-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.field-input {
  padding: 8px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-size: 12px;
}

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 4px 0 0;
}
</style>
