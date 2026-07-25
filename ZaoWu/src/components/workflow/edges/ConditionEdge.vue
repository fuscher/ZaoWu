<script setup lang="ts">
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from '@vue-flow/core'
import { computed } from 'vue'

const props = defineProps<EdgeProps>()

const path = computed(() => getSmoothStepPath(props))
</script>

<template>
  <BaseEdge
    :path="path[0]"
    :marker-end="markerEnd"
    :style="{ stroke: '#f59e0b', strokeWidth: 2 }"
    class="condition-edge"
  />
  <EdgeLabelRenderer>
    <div
      :style="{
        transform: `translate(-50%, -50%) translate(${path[1]}px, ${path[2]}px)`,
      }"
      class="condition-label"
    >
      {{ label || data?.sourcePort }}
    </div>
  </EdgeLabelRenderer>
</template>

<style scoped>
.condition-edge {
  transition: stroke 0.2s;
}

.condition-label {
  position: absolute;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  font-size: 10px;
  color: #f59e0b;
  pointer-events: none;
}
</style>
