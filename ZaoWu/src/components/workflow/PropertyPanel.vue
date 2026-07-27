<script setup lang="ts">
import { computed, defineAsyncComponent, ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import { apiPath } from '@/utils/api'
import type { Component } from 'vue'
import type { ToolDef } from '@/types/workflow'

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const { selectedNode } = storeToRefs(workflowStore)

const toolsList = ref<ToolDef[]>([])

async function loadTools() {
  try {
    const res = await fetch(apiPath('/workflows/tools'))
    const data = await res.json()
    if (data.ok && Array.isArray(data.tools)) {
      toolsList.value = data.tools
    }
  } catch {
    // 后端未实现 /api/workflows/tools 端点时静默回退
  }
}

onMounted(() => { loadTools() })

const componentMap: Record<string, Component> = {
  start: defineAsyncComponent(() => import('./configs/StartConfig.vue')),
  llm: defineAsyncComponent(() => import('./configs/LLMConfig.vue')),
  condition: defineAsyncComponent(() => import('./configs/ConditionConfig.vue')),
  tool: defineAsyncComponent(() => import('./configs/ToolConfig.vue')),
  loop: defineAsyncComponent(() => import('./configs/LoopConfig.vue')),
  end: defineAsyncComponent(() => import('./configs/EndConfig.vue')),
}

const configComponent = computed(() => {
  if (!selectedNode.value) return null
  return componentMap[selectedNode.value.type] ?? null
})
</script>

<template>
  <aside v-if="selectedNode" class="property-panel">
    <div class="property-header">
      <div>
        <h3 class="property-title">{{ selectedNode.label }}</h3>
        <p class="property-type">{{ t(`workflow.nodes.${selectedNode.type}`) }}</p>
      </div>
    </div>
    <Suspense>
      <component
        :is="configComponent"
        v-if="configComponent"
        :node="selectedNode"
        :tools="toolsList"
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

.property-loading {
  padding: 20px 0;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
