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

const outputFormat = computed({
  get: () => (props.node.config.outputFormat as 'text' | 'json' | 'markdown') ?? 'text',
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { outputFormat: v }),
})
</script>

<template>
  <div class="config-form">
    <label class="field-label">{{ t('workflow.config.outputFormat') }}</label>
    <select v-model="outputFormat" class="field-input">
      <option value="text">{{ t('workflow.config.formatText') }}</option>
      <option value="json">{{ t('workflow.config.formatJson') }}</option>
      <option value="markdown">{{ t('workflow.config.formatMarkdown') }}</option>
    </select>
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
</style>
