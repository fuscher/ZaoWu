<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import { X } from '@lucide/vue'
import { listRuns, type RunRecord } from '@/services/workflow'

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const { selectedNode, nodeRuntime } = storeToRefs(workflowStore)

const tab = ref<'inspect' | 'history'>('inspect')
const runs = ref<RunRecord[]>([])

const runtime = computed(() =>
  selectedNode.value ? nodeRuntime.value[selectedNode.value.id] : undefined
)

const inputsText = computed(() => JSON.stringify(runtime.value?.inputs ?? {}, null, 2))
const outputsText = computed(() => JSON.stringify(runtime.value?.outputs ?? {}, null, 2))

async function loadRuns() {
  const wf = workflowStore.workflow
  if (!wf) {
    runs.value = []
    return
  }
  try {
    runs.value = await listRuns(wf.id)
  } catch {
    runs.value = []
  }
}

// 切换到历史标签时加载运行记录
watch(tab, (newTab) => {
  if (newTab === 'history') loadRuns()
})

// 工作流切换时清空历史并回到检视标签
watch(() => workflowStore.workflow?.id, () => {
  runs.value = []
  tab.value = 'inspect'
})

function formatTime(ms: number): string {
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function statusText(status: string): string {
  const map: Record<string, string> = {
    running: t('workflow.runStatusRunning'),
    completed: t('workflow.runStatusCompleted'),
    errored: t('workflow.runStatusErrored'),
    stopped: t('workflow.runStatusErrored'),
  }
  return map[status] || status
}
</script>

<template>
  <div class="inspect-panel">
    <div class="inspect-header">
      <div class="inspect-tabs">
        <button :class="{ active: tab === 'inspect' }" @click="tab = 'inspect'">
          {{ t('workflow.inspectTitle') }}
        </button>
        <button :class="{ active: tab === 'history' }" @click="tab = 'history'">
          {{ t('workflow.runHistory') }}
        </button>
      </div>
      <button class="close-btn" @click="workflowStore.selectNode(null)">
        <X :size="14" />
      </button>
    </div>

    <!-- 节点检视标签页 -->
    <template v-if="tab === 'inspect'">
      <div v-if="selectedNode" class="inspect-body">
        <div class="inspect-row">
          <span class="inspect-label">{{ t('workflow.inspectNode') }}</span>
          <span class="inspect-value">{{ selectedNode.label }}</span>
        </div>
        <div class="inspect-row">
          <span class="inspect-label">{{ t('workflow.inspectStatus') }}</span>
          <span class="inspect-value status" :class="runtime?.status ?? 'idle'">
            {{ runtime?.status ?? 'idle' }}
          </span>
        </div>
        <div class="inspect-row">
          <span class="inspect-label">{{ t('workflow.inspectTokens') }}</span>
          <span class="inspect-value">{{ runtime?.tokens ?? '-' }}</span>
        </div>
        <div class="inspect-row">
          <span class="inspect-label">{{ t('workflow.inspectElapsed') }}</span>
          <span class="inspect-value">{{ runtime?.elapsedMs != null ? `${runtime.elapsedMs}ms` : '-' }}</span>
        </div>

        <div class="inspect-section">
          <span class="inspect-label">{{ t('workflow.inspectInputs') }}</span>
          <pre class="inspect-code">{{ inputsText }}</pre>
        </div>

        <div class="inspect-section">
          <span class="inspect-label">{{ t('workflow.inspectOutputs') }}</span>
          <pre class="inspect-code">{{ outputsText }}</pre>
        </div>

        <div v-if="runtime?.error" class="inspect-section">
          <span class="inspect-label">{{ t('workflow.inspectError') }}</span>
          <pre class="inspect-code error">{{ runtime.error }}</pre>
        </div>
      </div>

      <div v-else class="inspect-empty">
        {{ t('workflow.inspectHint') }}
      </div>
    </template>

    <!-- 运行历史标签页 -->
    <template v-else>
      <div class="inspect-body">
        <div v-if="runs.length === 0" class="inspect-empty">
          {{ t('workflow.noRuns') }}
        </div>
        <div v-else class="run-list">
          <div v-for="run in runs" :key="run.runId" class="run-item">
            <div class="run-header">
              <span class="run-status" :class="run.status">{{ statusText(run.status) }}</span>
              <span class="run-time">{{ formatTime(run.startTime) }}</span>
            </div>
            <div class="run-meta">
              <span>{{ t('workflow.runDuration') }}: {{ run.endTime ? `${run.endTime - run.startTime}ms` : '-' }}</span>
              <span>{{ t('workflow.runTokens') }}: {{ run.totalTokens || '-' }}</span>
            </div>
            <div v-if="run.error" class="run-error">{{ run.error }}</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.inspect-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.inspect-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px 0 0;
  border-bottom: 1px solid var(--border-subtle);
}

.inspect-tabs {
  display: flex;
}

.inspect-tabs button {
  padding: 10px 14px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color 0.2s, border-color 0.2s;
}

.inspect-tabs button:hover {
  color: var(--text-primary);
}

.inspect-tabs button.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.inspect-body {
  flex: 1;
  padding: 12px;
  overflow-y: auto;
}

.inspect-empty {
  padding: 20px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}

.inspect-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 12px;
}

.inspect-label {
  color: var(--text-secondary);
}

.inspect-value {
  font-weight: 500;
}

.inspect-value.status.idle {
  color: var(--text-tertiary);
}

.inspect-value.status.running {
  color: var(--accent);
}

.inspect-value.status.done {
  color: #22c55e;
}

.inspect-value.status.error {
  color: #ef4444;
}

.inspect-section {
  margin-top: 12px;
}

.inspect-code {
  margin: 6px 0 0;
  padding: 8px;
  border-radius: 6px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-subtle);
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 120px;
  overflow-y: auto;
}

.inspect-code.error {
  color: #ef4444;
}

/* 运行历史列表 */
.run-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.run-item {
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-subtle);
  font-size: 12px;
}

.run-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.run-status {
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
}

.run-status.running {
  color: var(--accent);
  background: rgba(59, 130, 246, 0.15);
}

.run-status.completed {
  color: #22c55e;
  background: rgba(34, 197, 94, 0.15);
}

.run-status.errored,
.run-status.stopped {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.15);
}

.run-time {
  color: var(--text-tertiary);
  font-size: 11px;
}

.run-meta {
  display: flex;
  gap: 16px;
  color: var(--text-secondary);
}

.run-error {
  margin-top: 4px;
  color: #ef4444;
  font-size: 11px;
  word-break: break-word;
}
</style>
