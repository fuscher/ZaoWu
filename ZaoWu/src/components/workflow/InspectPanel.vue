<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import { X } from '@lucide/vue'

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const { selectedNode, nodeRuntime } = storeToRefs(workflowStore)

const runtime = computed(() =>
  selectedNode.value ? nodeRuntime.value[selectedNode.value.id] : undefined
)

const inputsText = computed(() => JSON.stringify(runtime.value?.inputs ?? {}, null, 2))
const outputsText = computed(() => JSON.stringify(runtime.value?.outputs ?? {}, null, 2))
</script>

<template>
  <div class="inspect-panel">
    <div class="inspect-header">
      <h4>{{ t('workflow.inspectTitle') }}</h4>
      <button class="close-btn" @click="workflowStore.selectNode(null)">
        <X :size="14" />
      </button>
    </div>

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
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.inspect-header h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
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
</style>
