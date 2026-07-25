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
      mode: 'for',
      maxIterations: 10,
      circuitBreakerAction: 'break',
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
    <label class="field-label">{{ t('workflow.config.loopMode') }}</label>
    <select :value="cfg.mode" class="field-input" @change="update({ mode: ($event.target as HTMLSelectElement).value as any })">
      <option value="for">for</option>
      <option value="while">while (do-while)</option>
    </select>

    <template v-if="cfg.mode === 'for'">
      <label class="field-label">{{ t('workflow.config.iterateOver') }}</label>
      <input
        :value="cfg.iterateOver ?? '{{input}}'"
        class="field-input"
        type="text"
        @input="update({ iterateOver: ($event.target as HTMLInputElement).value })"
      />
    </template>

    <template v-else>
      <label class="field-label">{{ t('workflow.config.condition') }}</label>
      <input
        :value="cfg.condition ?? 'False'"
        class="field-input"
        type="text"
        @input="update({ condition: ($event.target as HTMLInputElement).value })"
      />
    </template>

    <label class="field-label">{{ t('workflow.config.maxIterations') }}</label>
    <input
      :value="cfg.maxIterations"
      class="field-input"
      type="number"
      min="1"
      @input="update({ maxIterations: Number(($event.target as HTMLInputElement).value) })"
    />

    <label class="field-label">{{ t('workflow.config.circuitBreakerAction') }}</label>
    <select :value="cfg.circuitBreakerAction" class="field-input" @change="update({ circuitBreakerAction: ($event.target as HTMLSelectElement).value as any })">
      <option value="break">break</option>
      <option value="error">error</option>
    </select>

    <p class="hint">{{ t('workflow.config.loopHint') }}</p>
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
  margin: 8px 0 0;
}
</style>
