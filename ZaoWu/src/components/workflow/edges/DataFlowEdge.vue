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
        stroke: 'var(--accent)',
        glow: 'var(--accent)',
        particle: 'var(--accent-hover, var(--accent))',
        dash: 'var(--accent)',
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
        stroke: 'var(--text-tertiary)',
        glow: 'rgba(128, 128, 128, 0.35)',
        particle: 'var(--text-secondary)',
        dash: 'var(--text-secondary)',
      }
  }
})
</script>

<template>
  <g class="data-flow-edge" :class="[edgeStatus, { active: isActive, selected }]">
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
    />
    <!-- 运行时流动虚线动画 -->
    <path
      v-if="isActive"
      :d="bezier.path"
      class="edge-flow"
      fill="none"
      :stroke="theme.dash"
      stroke-width="3"
      stroke-linecap="round"
      stroke-dasharray="8 12"
    />
    <!-- 流动粒子 -->
    <circle v-if="isActive" r="3.5" :fill="theme.particle" class="edge-particle">
      <animateMotion dur="1.2s" repeatCount="indefinite" :path="bezier.path" />
    </circle>
  </g>

  <EdgeLabelRenderer v-if="isActive">
    <div
      class="data-flow-label"
      :style="{
        transform: `translate(-50%, -50%) translate(${bezier.centerX}px, ${bezier.centerY}px)`,
      }"
    >
      <span class="pulse-ring" />
    </div>
  </EdgeLabelRenderer>
</template>

<style scoped>
.data-flow-edge {
  pointer-events: stroke;
}

.edge-path {
  transition: stroke 0.25s ease, stroke-width 0.2s ease, opacity 0.25s ease;
  opacity: 0.8;
}

.data-flow-edge:hover .edge-path {
  stroke-width: 3.5;
  opacity: 1;
}

.edge-glow {
  opacity: 0;
  transition: opacity 0.25s ease;
  pointer-events: none;
}

.data-flow-edge:hover .edge-glow,
.data-flow-edge.active .edge-glow {
  opacity: 0.28;
}

.data-flow-edge.active .edge-glow {
  opacity: 0.45;
}

.data-flow-edge.selected .edge-path {
  stroke: var(--accent) !important;
  stroke-width: 3.5;
  opacity: 1;
}

.data-flow-edge.selected .edge-glow {
  opacity: 0.55;
}

/* 流动虚线动画 */
.edge-flow {
  opacity: 0.9;
  pointer-events: none;
  animation: dash-flow 0.9s linear infinite;
}

@keyframes dash-flow {
  from {
    stroke-dashoffset: 20;
  }
  to {
    stroke-dashoffset: 0;
  }
}

/* 流动粒子：微微发光 */
.edge-particle {
  filter: drop-shadow(0 0 4px currentColor);
  pointer-events: none;
}

/* 中点脉冲标签 */
.data-flow-label {
  position: absolute;
  pointer-events: none;
  width: 12px;
  height: 12px;
}

.pulse-ring {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.6;
  animation: node-pulse 1s ease-out infinite;
}

@keyframes node-pulse {
  0% {
    transform: scale(0.6);
    opacity: 0.8;
  }
  100% {
    transform: scale(2.2);
    opacity: 0;
  }
}
</style>
