<script setup lang="ts">
import { EdgeLabelRenderer, type EdgeProps } from '@vue-flow/core'
import { computed } from 'vue'
import { getComfyBezierPath } from './edge-path'
import { useWorkflowStore } from '@/stores/workflow'

type EdgeStatus = 'idle' | 'running' | 'done' | 'error'

const props = defineProps<EdgeProps>()
const workflowStore = useWorkflowStore()

const bezier = computed(() =>
  getComfyBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
    sourcePosition: props.sourcePosition,
    targetPosition: props.targetPosition,
  }),
)

const isActive = computed(() => Boolean(props.data?.active))

const edgeStatus = computed<EdgeStatus>(() => {
  if (isActive.value) return 'running'
  const sourceStatus = workflowStore.nodeRuntime[props.source]?.status
  if (sourceStatus === 'error') return 'error'
  if (sourceStatus === 'done') return 'done'
  return 'idle'
})

const theme = computed(() => {
  switch (edgeStatus.value) {
    case 'running':
      return {
        stroke: 'var(--warning)',
        glow: 'var(--warning)',
        particle: 'var(--warning)',
        dash: 'var(--warning)',
      }
    case 'done':
      return {
        stroke: 'var(--success)',
        glow: 'var(--success)',
        particle: 'var(--success)',
        dash: 'var(--success)',
      }
    case 'error':
      return {
        stroke: 'var(--danger)',
        glow: 'var(--danger)',
        particle: 'var(--danger)',
        dash: 'var(--danger)',
      }
    default:
      return {
        stroke: 'var(--warning)',
        glow: 'rgba(255, 189, 46, 0.35)',
        particle: 'var(--warning)',
        dash: 'var(--warning)',
      }
  }
})

const displayLabel = computed(() => props.label || props.data?.sourcePort)
</script>

<template>
  <g class="condition-edge" :class="[edgeStatus, { active: isActive, selected }]">
    <!-- 外发光层 -->
    <path
      :d="bezier.path"
      class="edge-glow"
      fill="none"
      :stroke="theme.glow"
      stroke-width="6"
      stroke-linecap="round"
    />
    <!-- 主体连线 -->
    <path
      :d="bezier.path"
      class="edge-path"
      fill="none"
      :stroke="theme.stroke"
      stroke-width="2.5"
      stroke-linecap="round"
      stroke-dasharray="none"
    />
    <!-- 运行时流动虚线 -->
    <path
      v-if="isActive"
      :d="bezier.path"
      class="edge-flow"
      fill="none"
      :stroke="theme.dash"
      stroke-width="3"
      stroke-linecap="round"
      stroke-dasharray="6 10"
    />
    <!-- 流动粒子 -->
    <circle v-if="isActive" r="3.5" :fill="theme.particle" class="edge-particle">
      <animateMotion dur="1.2s" repeatCount="indefinite" :path="bezier.path" />
    </circle>
  </g>

  <EdgeLabelRenderer>
    <div
      class="condition-label"
      :class="{ active: isActive }"
      :style="{
        transform: `translate(-50%, -50%) translate(${bezier.centerX}px, ${bezier.centerY}px)`,
      }"
    >
      {{ displayLabel }}
    </div>
  </EdgeLabelRenderer>
</template>

<style scoped>
.condition-edge {
  pointer-events: stroke;
}

.edge-path {
  transition: stroke 0.25s ease, stroke-width 0.2s ease, opacity 0.25s ease;
  opacity: 0.85;
}

.condition-edge:hover .edge-path {
  stroke-width: 3.5;
  opacity: 1;
}

.edge-glow {
  opacity: 0;
  transition: opacity 0.25s ease;
  pointer-events: none;
}

.condition-edge:hover .edge-glow,
.condition-edge.active .edge-glow {
  opacity: 0.3;
}

.condition-edge.active .edge-glow {
  opacity: 0.45;
}

.condition-edge.selected .edge-path {
  stroke: var(--accent) !important;
  stroke-width: 3.5;
  opacity: 1;
}

.condition-edge.selected .edge-glow {
  opacity: 0.55;
}

/* 流动虚线动画 */
.edge-flow {
  opacity: 0.95;
  pointer-events: none;
  animation: dash-flow 0.9s linear infinite;
}

@keyframes dash-flow {
  from {
    stroke-dashoffset: 16;
  }
  to {
    stroke-dashoffset: 0;
  }
}

.edge-particle {
  filter: drop-shadow(0 0 4px currentColor);
  pointer-events: none;
}

.condition-label {
  position: absolute;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  font-size: 10px;
  font-weight: 600;
  color: var(--warning);
  pointer-events: none;
  box-shadow: var(--shadow-sm);
  transition: transform 0.2s ease, box-shadow 0.2s ease, color 0.2s ease;
}

.condition-label.active {
  color: var(--warning);
  box-shadow: 0 0 0 2px var(--warning-bg), var(--shadow-sm);
  animation: label-pop 0.3s ease;
}

@keyframes label-pop {
  0% {
    transform: translate(-50%, -50%) scale(0.9);
  }
  100% {
    transform: translate(-50%, -50%) scale(1);
  }
}
</style>
