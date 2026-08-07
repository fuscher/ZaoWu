<script setup lang="ts">
import { computed, ref } from 'vue'
import { Brain, Wrench, Archive, RotateCw, ArrowLeftRight, Check, AlertTriangle, Info, Ban, ChevronDown, ChevronRight } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { PhaseNode, PhaseName, NoticePayload } from '@/types'

const props = defineProps<{
  /** 当前消息的 phase 节点链（消费 phaseHistoryFor(message.id)） */
  phases: PhaseNode[]
  isStreaming?: boolean
}>()

const { t } = useI18n()
const expanded = ref(false)

const phaseIcon = (phase: PhaseName) => {
  switch (phase) {
    case 'thinking': return Brain
    case 'tool': return Wrench
    case 'compacting': return Archive
    case 'retrying': return RotateCw
    case 'handoff': return ArrowLeftRight
    case 'done': return Check
  }
}

const phaseKey = (phase: PhaseName) => `agent.phase.${phase}`

const noticeIcon = (n: NoticePayload) => {
  switch (n.level) {
    case 'warn': return AlertTriangle
    case 'blocked': return Ban
    default: return Info
  }
}

/** 折叠态：展示当前（最后一个）节点 */
const current = computed(() => props.phases[props.phases.length - 1] as PhaseNode | undefined)

function fmtTime(ts: number): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}
</script>

<template>
  <div v-if="phases.length > 0" class="phase-strip" :class="{ streaming: isStreaming }">
    <button class="phase-toggle" :class="{ expanded }" @click="expanded = !expanded">
      <ChevronDown v-if="expanded" :size="12" />
      <ChevronRight v-else :size="12" />
    </button>

    <div v-if="!expanded && current" class="phase-current">
      <component :is="phaseIcon(current.phase)" :size="12" />
      <span>{{ t(phaseKey(current.phase)) }}</span>
      <span v-if="current.detail" class="phase-detail">{{ current.detail }}</span>
      <AlertTriangle
        v-if="current.notices?.some((n) => n.level === 'warn' || n.level === 'blocked')"
        :size="12"
        class="warn-icon"
      />
    </div>

    <div v-else class="phase-history">
      <div v-for="(node, i) in phases" :key="i" class="phase-node">
        <span class="node-icon"><component :is="phaseIcon(node.phase)" :size="11" /></span>
        <span class="node-label">{{ t(phaseKey(node.phase)) }}</span>
        <span v-if="node.detail" class="phase-detail">{{ node.detail }}</span>
        <span class="node-time">{{ fmtTime(node.ts) }}</span>
        <div v-if="node.notices && node.notices.length" class="node-notices">
          <div v-for="(n, j) in node.notices" :key="j" class="node-notice" :class="n.level">
            <component :is="noticeIcon(n)" :size="11" />
            <span>{{ n.message }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.phase-strip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  margin-bottom: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--bg-glass);
  font-size: 11.5px;
  color: var(--text-tertiary);
}

.phase-strip.streaming {
  border-color: var(--accent-muted);
}

.phase-toggle {
  display: inline-flex;
  align-items: center;
  padding: 0;
  border: none;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  flex-shrink: 0;
}

.phase-toggle.expanded {
  color: var(--accent);
}

.phase-current {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-secondary);
  overflow: hidden;
  white-space: nowrap;
}

.phase-detail {
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 160px;
}

.warn-icon {
  color: var(--warning, #d97706);
  flex-shrink: 0;
}

.phase-history {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.phase-node {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}

.node-icon {
  display: inline-flex;
  color: var(--accent);
  flex-shrink: 0;
}

.node-label {
  color: var(--text-secondary);
}

.node-time {
  font-size: 10.5px;
  color: var(--text-tertiary);
}

.node-notices {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding-left: 16px;
}

.node-notice {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-secondary);
}

.node-notice.warn {
  color: var(--warning, #d97706);
}

.node-notice.blocked {
  color: var(--danger);
}
</style>
