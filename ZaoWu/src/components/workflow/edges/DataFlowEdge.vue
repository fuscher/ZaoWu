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
    :style="{ stroke: '#94a3b8', strokeWidth: 2 }"
    class="data-flow-edge"
  />
  <EdgeLabelRenderer v-if="data?.active">
    <div
      :style="{
        transform: `translate(-50%, -50%) translate(${path[1]}px, ${path[2]}px)`,
      }"
      class="data-flow-pulse"
    >
      <div class="pulse-dot" />
    </div>
  </EdgeLabelRenderer>
</template>

<style scoped>
.data-flow-edge {
  transition: stroke 0.2s;
}

.data-flow-pulse {
  position: absolute;
  pointer-events: none;
}

.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent, #3b82f6);
  box-shadow: 0 0 8px var(--accent, #3b82f6);
  animation: flow-move 1s linear infinite;
}

@keyframes flow-move {
  0% {
    opacity: 1;
    transform: scale(1);
  }
  100% {
    opacity: 0;
    transform: scale(2);
  }
}
</style>
