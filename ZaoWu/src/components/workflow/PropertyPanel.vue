<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import type { Component } from 'vue'

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const { selectedNode } = storeToRefs(workflowStore)

const componentMap: Record<string, () => Promise<{ default: Component }>> = {
  start: () => import('./configs/StartConfig.vue'),
  llm: () => import('./configs/LLMConfig.vue'),
  condition: () => import('./configs/ConditionConfig.vue'),
  tool: () => import('./configs/ToolConfig.vue'),
  router: () => import('./configs/RouterConfig.vue'),
  loop: () => import('./configs/LoopConfig.vue'),
  end: () => import('./configs/EndConfig.vue'),
}

const configComponent = computed(() => {
  if (!selectedNode.value) return null
  return componentMap[selectedNode.value.type] ?? null
})
</script>

<template>
  <aside v-if="selectedNode" class="property-panel">
    <h3 class="property-title">{{ selectedNode.label }}</h3>
    <p class="property-type">{{ t(`workflow.nodes.${selectedNode.type}`) }}</p>
    <Suspense>
      <component
        :is="configComponent"
        v-if="configComponent"
        :node="selectedNode"
      />
      <template #fallback>
        <div class="property-loading">{{ t('workflow.loadingConfig') }}</div>
      </template>
    </Suspense>
  </aside>
  <aside v-else class="property-panel empty">
    <p>{{ t('workflow.selectNodeHint') }}</p>
  </aside>
</template>

<style scoped>
.property-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 14px;
  background: var(--bg-secondary);
  overflow-y: auto;
}

.property-panel.empty {
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  font-size: 13px;
}

.property-title {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
}

.property-type {
  margin: 0 0 14px;
  font-size: 12px;
  color: var(--text-tertiary);
  text-transform: capitalize;
}

.property-loading {
  padding: 20px 0;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
