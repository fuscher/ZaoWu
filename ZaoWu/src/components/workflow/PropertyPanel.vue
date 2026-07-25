<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import { Trash2 } from '@lucide/vue'
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

function deleteNode() {
  if (!selectedNode.value) return
  const nodeId = selectedNode.value.id
  const newNodes = workflowStore.nodes.filter((n) => n.id !== nodeId)
  const newEdges = workflowStore.edges.filter(
    (e) => e.source !== nodeId && e.target !== nodeId,
  )
  workflowStore.setNodes(newNodes)
  workflowStore.setEdges(newEdges)
  workflowStore.selectNode(null)
}
</script>

<template>
  <aside v-if="selectedNode" class="property-panel">
    <div class="property-header">
      <div>
        <h3 class="property-title">{{ selectedNode.label }}</h3>
        <p class="property-type">{{ t(`workflow.nodes.${selectedNode.type}`) }}</p>
      </div>
      <button
        class="delete-node-btn"
        :title="t('workflow.deleteNode')"
        @click="deleteNode"
      >
        <Trash2 :size="14" />
      </button>
    </div>
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

.property-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}

.property-title {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
}

.property-type {
  margin: 0;
  font-size: 12px;
  color: var(--text-tertiary);
  text-transform: capitalize;
}

.delete-node-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
}

.delete-node-btn:hover {
  background: var(--bg-hover);
}

.property-loading {
  padding: 20px 0;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
