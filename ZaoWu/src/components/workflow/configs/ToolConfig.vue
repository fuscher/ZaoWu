<script setup lang="ts">
import { computed } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import type { WorkflowNode } from '@/types/workflow'

const props = defineProps<{
  node: WorkflowNode
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()

const toolName = computed({
  get: () => (props.node.config.toolName as string) ?? '',
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { toolName: v }),
})

const toolArgsText = computed({
  get: () => JSON.stringify((props.node.config.toolArgs as Record<string, string>) ?? {}, null, 2),
  set: (v) => {
    try {
      const parsed = JSON.parse(v)
      workflowStore.updateNodeConfig(props.node.id, { toolArgs: parsed })
    } catch {
      // ignore invalid JSON while typing
    }
  },
})
</script>

<template>
  <div class="config-form">
    <label class="field-label">{{ t('workflow.config.toolName') }}</label>
    <input v-model="toolName" class="field-input" type="text" />

    <label class="field-label">{{ t('workflow.config.toolArgs') }}</label>
    <textarea v-model="toolArgsText" class="field-input mono" rows="6" />
  </div>
</template>

<style scoped>
.config-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
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

.field-input.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
</style>
