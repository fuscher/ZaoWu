<script setup lang="ts">
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from '@vue-flow/core'
import { computed } from 'vue'

const props = defineProps<EdgeProps>()

const path = computed(() => getSmoothStepPath(props))
const isBreak = computed(() => props.sourceHandleId === 'break')
</script>

<template>
  <BaseEdge
    :path="path[0]"
    :marker-end="markerEnd"
    :style="{ stroke: isBreak ? '#ef4444' : '#22c55e', strokeWidth: 2, strokeDasharray: '5,5' }"
    class="break-continue-edge"
  />
  <EdgeLabelRenderer>
    <div
      :style="{
        transform: `translate(-50%, -50%) translate(${path[1]}px, ${path[2]}px)`,
      }"
      class="break-continue-label"
      :class="isBreak ? 'break' : 'continue'"
    >
      {{ label || sourceHandleId }}
    </div>
  </EdgeLabelRenderer>
</template>

<style scoped>
.break-continue-edge {
  transition: stroke 0.2s;
}

.break-continue-label {
  position: absolute;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  font-size: 10px;
  pointer-events: none;
}

.break-continue-label.break {
  color: #ef4444;
}

.break-continue-label.continue {
  color: #22c55e;
}
</style>
