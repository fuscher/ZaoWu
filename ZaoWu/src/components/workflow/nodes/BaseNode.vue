<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'
import {
  Bot,
  Check,
  GitBranch,
  Hammer,
  Play,
  Square,
  Workflow,
  X,
  type LucideIcon,
} from '@lucide/vue'
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
    <!-- 运行时扫描光效 -->
    <div v-if="props.status === 'running'" class="node-scan-glow" />

    <!-- 完成/错误：状态角标 -->
    <div v-if="props.status === 'done'" class="status-badge badge-done">
      <Check :size="10" stroke-width="3" />
    </div>
    <div v-if="props.status === 'error'" class="status-badge badge-error">
      <X :size="10" stroke-width="3" />
    </div>

    <div class="node-header">
      <component :is="iconComponent" class="node-icon" :size="16" />
      <span class="node-title">{{ props.label }}</span>
      <span v-if="props.tokens" class="token-badge">{{ props.tokens }}T</span>
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
  min-width: 170px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  overflow: visible;
  font-size: 12px;
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.25s ease, border-color 0.25s ease, transform 0.15s ease;
}

.base-node:hover {
  box-shadow: var(--shadow);
  transform: translateY(-1px);
}

/* ── 状态色 ── */
.status-running {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 1px var(--accent-border), 0 0 20px var(--accent-muted);
}

.status-done {
  border-color: var(--success);
  box-shadow: 0 0 0 1px var(--success), 0 0 14px var(--success-muted);
}

.status-error {
  border-color: var(--danger);
  box-shadow: 0 0 0 1px var(--danger), 0 0 14px var(--danger-bg);
  animation: error-shake 0.4s ease;
}

@keyframes error-shake {
  0%,
  100% {
    transform: translateX(0);
  }
  25% {
    transform: translateX(-3px);
  }
  75% {
    transform: translateX(3px);
  }
}

/* ── 扫描光效 ── */
.node-scan-glow {
  position: absolute;
  inset: -2px;
  border-radius: 13px;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

.node-scan-glow::before {
  content: '';
  position: absolute;
  top: 0;
  left: -50%;
  width: 50%;
  height: 100%;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(100, 210, 255, 0.22),
    transparent
  );
  animation: scan-sweep 1.6s linear infinite;
}

@keyframes scan-sweep {
  0% {
    left: -50%;
  }
  100% {
    left: 150%;
  }
}

/* ── 状态角标 ── */
.status-badge {
  position: absolute;
  top: -7px;
  right: -7px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  z-index: 2;
  box-shadow: var(--shadow-sm);
  animation: badge-pop 0.3s ease;
}

.badge-done {
  background: var(--success);
}

.badge-error {
  background: var(--danger);
}

@keyframes badge-pop {
  0% {
    transform: scale(0);
  }
  70% {
    transform: scale(1.15);
  }
  100% {
    transform: scale(1);
  }
}

/* ── 头部 ── */
.node-header {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
  border-radius: 12px 12px 0 0;
}

.node-icon {
  flex-shrink: 0;
  color: var(--accent);
}

.node-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.token-badge {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 2px 6px;
  border-radius: 999px;
}

.node-body {
  position: relative;
  z-index: 1;
  padding: 10px 12px;
  min-height: 32px;
  border-radius: 0 0 12px 12px;
}
</style>
