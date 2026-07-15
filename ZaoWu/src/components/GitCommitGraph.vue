<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '@/i18n'
import type { GitCommit } from '@/types'

const props = defineProps<{
  commits: GitCommit[]
  hasMore: boolean
}>()

const emit = defineEmits<{ loadMore: [] }>()
const { t } = useI18n()
const containerRef = ref<HTMLElement | null>(null)
const NODE_RADIUS = 5
const LINE_HEIGHT = 48
const PADDING_LEFT = 14
const PADDING_TOP = 16

const locals = computed(() =>
  props.commits.filter(c => c.isLocalTip)
)

const hasContent = computed(() => props.commits.length > 0)

function onScroll(e: Event) {
  const el = e.target as HTMLElement
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 20 && props.hasMore) {
    emit('loadMore')
  }
}

function copyHash(hash: string) {
  navigator.clipboard.writeText(hash).catch(() => {})
}
</script>

<template>
  <div v-if="!hasContent" class="graph-empty">{{ t('git.commitCount', { count: 0 }) }}</div>
  <div v-else ref="containerRef" class="graph-container" @scroll="onScroll">
    <svg
      :width="280"
      :height="commits.length * LINE_HEIGHT + PADDING_TOP + 16"
      class="graph-svg"
    >
      <g v-for="(c, i) in commits" :key="c.hash">
        <line
          v-if="i < commits.length - 1"
          :x1="PADDING_LEFT"
          :y1="PADDING_TOP + i * LINE_HEIGHT + NODE_RADIUS"
          :x2="PADDING_LEFT"
          :y2="PADDING_TOP + (i + 1) * LINE_HEIGHT - NODE_RADIUS"
          :stroke="c.isLocalTip ? 'var(--accent)' : c.isRemoteTip ? '#1565c0' : 'var(--text-tertiary)'"
          stroke-width="1.5"
        />
        <circle
          :cx="PADDING_LEFT"
          :cy="PADDING_TOP + i * LINE_HEIGHT"
          :r="NODE_RADIUS"
          :fill="c.isLocalTip ? 'var(--accent)' : c.isRemoteTip ? '#1565c0' : 'var(--text-tertiary)'"
          :opacity="c.isLocalTip || c.isRemoteTip ? 1 : 0.6"
          style="cursor: pointer"
          @click="copyHash(c.hash)"
          :title="t('git.localTip')"
        />
        <text
          :x="PADDING_LEFT + 14"
          :y="PADDING_TOP + i * LINE_HEIGHT + 4"
          fill="var(--text-primary)"
          font-size="11"
          font-family="Consolas, Monaco, monospace"
          style="cursor: pointer"
          @click="copyHash(c.hash)"
        >
          <tspan fill="var(--text-tertiary)" font-size="10">{{ c.shortHash }} </tspan>
          {{ c.message }}
        </text>
        <text
          v-if="c.isLocalTip"
          :x="PADDING_LEFT + 14"
          :y="PADDING_TOP + i * LINE_HEIGHT + 18"
          fill="var(--accent)"
          font-size="9"
        >{{ t('git.localTip') }}</text>
        <text
          v-else-if="c.isRemoteTip"
          :x="PADDING_LEFT + 14"
          :y="PADDING_TOP + i * LINE_HEIGHT + 18"
          fill="#1565c0"
          font-size="9"
        >{{ t('git.remoteTip') }}</text>
      </g>
    </svg>
    <div v-if="hasMore" class="graph-more" @click="emit('loadMore')">
      {{ t('git.commitCount', { count: '...' }).replace('...', '') }}...
    </div>
  </div>
</template>

<style scoped>
.graph-container {
  max-height: 360px;
  overflow-y: auto;
  padding: 4px 0;
}

.graph-empty {
  padding: 16px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}

.graph-svg {
  display: block;
  min-width: 100%;
}

.graph-more {
  padding: 6px;
  text-align: center;
  color: var(--accent);
  font-size: 11px;
  cursor: pointer;
}

.graph-more:hover {
  color: var(--text-primary);
}
</style>
