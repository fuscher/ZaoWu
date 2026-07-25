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

const routerMode = computed({
  get: () => (props.node.config.routerMode as 'semantic' | 'regex' | 'code') ?? 'regex',
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { routerMode: v }),
})

const categoriesText = computed({
  get: () => JSON.stringify((props.node.config.routeCategories as unknown[]) ?? [], null, 2),
  set: (v) => {
    try {
      const parsed = JSON.parse(v)
      workflowStore.updateNodeConfig(props.node.id, { routeCategories: parsed })
    } catch {
      // ignore invalid JSON while typing
    }
  },
})
</script>

<template>
  <div class="config-form">
    <label class="field-label">{{ t('workflow.config.routerMode') }}</label>
    <select v-model="routerMode" class="field-input">
      <option value="regex">regex</option>
      <option value="code">code</option>
      <option value="semantic">semantic</option>
    </select>

    <label class="field-label">{{ t('workflow.config.routeCategories') }}</label>
    <textarea v-model="categoriesText" class="field-input mono" rows="8" />

    <p class="hint">{{ t('workflow.config.routerHint') }}</p>
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

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 0;
}
</style>
