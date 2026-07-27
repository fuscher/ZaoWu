<script setup lang="ts">
import { computed, ref } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import type { WorkflowNode } from '@/types/workflow'

const props = defineProps<{
  node: WorkflowNode
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()

const endMode = computed({
  get: () => (props.node.config.endMode as 'none' | 'log') ?? 'log',
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { endMode: v }),
})

const logFormat = computed({
  get: () => (props.node.config.logFormat as 'txt' | 'json' | 'markdown') ?? 'txt',
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { logFormat: v }),
})

const logDir = computed({
  get: () => (props.node.config.logDir as string) ?? './workflow_logs',
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { logDir: v }),
})

const logName = computed({
  get: () => (props.node.config.logName as string) ?? '',
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { logName: v }),
})
</script>

<template>
  <div class="config-form">
    <label class="field-label">{{ t('workflow.config.endMode') }}</label>
    <select v-model="endMode" class="field-input">
      <option value="none">{{ t('workflow.config.endModeNone') }}</option>
      <option value="log">{{ t('workflow.config.endModeLog') }}</option>
    </select>

    <template v-if="endMode === 'log'">
      <label class="field-label">{{ t('workflow.config.logDir') }}</label>
      <input v-model="logDir" class="field-input" type="text" />

      <label class="field-label">{{ t('workflow.config.logFormat') }}</label>
      <select v-model="logFormat" class="field-input">
        <option value="txt">{{ t('workflow.config.logFormatTxt') }}</option>
        <option value="json">{{ t('workflow.config.logFormatJson') }}</option>
        <option value="markdown">{{ t('workflow.config.logFormatMarkdown') }}</option>
      </select>

      <label class="field-label">{{ t('workflow.config.logName') }}</label>
      <input
        v-model="logName"
        class="field-input"
        type="text"
        :placeholder="t('workflow.config.logNameHint')"
      />
      <p class="hint">{{ t('workflow.config.logNameHint') }}</p>
    </template>
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

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 0;
}
</style>
