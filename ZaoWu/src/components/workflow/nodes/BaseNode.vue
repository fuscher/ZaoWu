<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'
import { Bot, GitBranch, Hammer, Play, Square, Workflow, type LucideIcon } from '@lucide/vue'
import { computed } from 'vue'
import type { NodeStatus } from '@/types/workflow'
import { useI18n } from '@/i18n'

const workflowIconMap: Record<string, LucideIcon> = {
  Bot,
  GitBranch,
  Hammer,
  Play,
  Square,
  Workflow,
}

const props = defineProps<{
  id: string
  status: NodeStatus
  tokens?: number
  label: string
  iconName: keyof typeof workflowIconMap
  inputs?: string[]
  outputs?: string[]
}>()

const { t } = useI18n()

const iconComponent = computed(() => workflowIconMap[props.iconName])

function portTitle(portId: string, dir: 'input' | 'output'): string {
  const dirLabel = t(`workflow.ports.${dir}`)
  const name = t(`workflow.ports.${portId}`)
  return `${name}（${dirLabel}）`
}
</script>

<template>
  <div class="base-node" :class="`status-${props.status}`">
    <div v-if="props.status === 'running'" class="node-glow" />

    <div class="node-header">
      <component :is="iconComponent" class="node-icon" :size="16" />
      <span>{{ props.label }}</span>
      <span v-if="props.tokens" class="token-badge">{{ props.tokens }}T</span>
      <span class="status-dot" :class="props.status" />
    </div>

    <div class="node-body">
      <slot />
    </div>

    <template v-if="props.inputs">
      <Handle
        v-for="(input, idx) in props.inputs"
        :key="`in-${idx}`"
        type="target"
        :position="Position.Left"
        :id="input"
        :title="portTitle(input, 'input')"
        :style="{ top: `${((idx + 1) / (props.inputs.length + 1)) * 100}%` }"
      />
    </template>
    <template v-if="props.outputs">
      <Handle
        v-for="(output, idx) in props.outputs"
        :key="`out-${idx}`"
        type="source"
        :position="Position.Right"
        :id="output"
        :title="portTitle(output, 'output')"
        :style="{ top: `${((idx + 1) / (props.outputs.length + 1)) * 100}%` }"
      />
    </template>
  </div>
</template>

<style scoped>
.base-node {
  position: relative;
  min-width: 160px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  overflow: hidden;
  font-size: 12px;
  color: var(--text-primary);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.status-running {
  border-color: var(--accent);
}

.status-done {
  border-color: #22c55e;
}

.status-error {
  border-color: #ef4444;
}

.node-glow {
  position: absolute;
  inset: -2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0.5;
  animation: glow-sweep 1.5s linear infinite;
  pointer-events: none;
}

@keyframes glow-sweep {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}

.node-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
}

.node-icon {
  flex-shrink: 0;
  color: var(--accent);
}

.token-badge {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-tertiary);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-tertiary);
}

.status-dot.running {
  background: var(--accent);
  animation: pulse 1s ease-in-out infinite;
}

.status-dot.done {
  background: #22c55e;
}

.status-dot.error {
  background: #ef4444;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

.node-body {
  padding: 10px;
  min-height: 32px;
}
</style>
