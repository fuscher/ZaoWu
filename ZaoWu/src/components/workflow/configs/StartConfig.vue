<script setup lang="ts">
import { computed, watch } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import type { WorkflowNode } from '@/types/workflow'

const props = defineProps<{
  node: WorkflowNode
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()

const defaultValue = computed({
  get: () => (props.node.config.defaultValue as string) ?? '',
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { defaultValue: v }),
})

const executionMode = computed({
  get: () => (props.node.config.executionMode as 'parallel' | 'ordered') ?? 'parallel',
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { executionMode: v }),
})

const orderedTargets = computed<string[]>({
  get: () => (props.node.config.orderedTargets as string[]) ?? [],
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { orderedTargets: v }),
})

// 从 Start 出发的边对应的下游节点
interface TargetInfo {
  id: string
  label: string
  type: string
}

const downstreamTargets = computed<TargetInfo[]>(() => {
  const nodes = workflowStore.nodes
  const edges = workflowStore.edges
  const nodeMap = new Map(nodes.map((n) => [n.id, n]))
  return edges
    .filter((e) => e.source === props.node.id)
    .map((e) => {
      const targetNode = nodeMap.get(e.target)
      return {
        id: e.target,
        label: targetNode?.label ?? e.target,
        type: targetNode?.type ?? '',
      }
    })
})

const unlistedTargets = computed(() =>
  downstreamTargets.value.filter((t) => !orderedTargets.value.includes(t.id)),
)

function moveTarget(idx: number, delta: number) {
  const list = [...orderedTargets.value]
  const newIdx = idx + delta
  const tmp = list[idx]!
  list[idx] = list[newIdx]!
  list[newIdx] = tmp
  orderedTargets.value = list
}

function addTarget(id: string) {
  orderedTargets.value = [...orderedTargets.value, id]
}

function removeTarget(idx: number) {
  orderedTargets.value = orderedTargets.value.filter((_, i) => i !== idx)
}

// 切换到 ordered 模式时自动填充未列出的下游目标
watch(executionMode, (newMode) => {
  if (newMode === 'ordered') {
    const existing = orderedTargets.value
    const streamIds = downstreamTargets.value.map((t) => t.id)
    const missing = streamIds.filter((id) => !existing.includes(id))
    if (missing.length > 0) {
      orderedTargets.value = [...existing, ...missing]
    }
  }
})
</script>

<template>
  <div class="config-form">
    <label class="field-label">{{ t('workflow.config.defaultValue') }}</label>
    <textarea v-model="defaultValue" class="field-input" rows="4" />

    <label class="field-label">{{ t('workflow.config.executionMode') }}</label>
    <select v-model="executionMode" class="field-input">
      <option value="parallel">{{ t('workflow.config.executionParallel') }}</option>
      <option value="ordered">{{ t('workflow.config.executionOrdered') }}</option>
    </select>

    <!-- 顺序执行目标列表 -->
    <template v-if="executionMode === 'ordered'">
      <label class="field-label">{{ t('workflow.config.orderedTargets') }}</label>
      <p class="hint">{{ t('workflow.config.orderedTargetsHint') }}</p>

      <div v-if="downstreamTargets.length === 0" class="empty-hint">
        {{ t('workflow.config.noDownstreamTargets') }}
      </div>

      <div v-else class="ordered-list">
        <div
          v-for="(targetId, idx) in orderedTargets"
          :key="targetId"
          class="ordered-item"
        >
          <span class="order-idx">{{ idx + 1 }}</span>
          <span class="order-label">{{ workflowStore.nodes.find(n => n.id === targetId)?.label ?? targetId }}</span>
          <div class="order-actions">
            <button
              class="order-btn"
              :disabled="idx === 0"
              :title="t('workflow.config.moveUp')"
              @click="moveTarget(idx, -1)"
            >&#9650;</button>
            <button
              class="order-btn"
              :disabled="idx === orderedTargets.length - 1"
              :title="t('workflow.config.moveDown')"
              @click="moveTarget(idx, 1)"
            >&#9660;</button>
            <button
              class="order-btn danger"
              :title="t('workflow.config.removeFromOrder')"
              @click="removeTarget(idx)"
            >&times;</button>
          </div>
        </div>

        <div
          v-for="target in unlistedTargets"
          :key="target.id"
          class="ordered-item unlisted"
        >
          <span class="order-label">{{ target.label }}</span>
          <button class="order-btn add" @click="addTarget(target.id)">+ {{ t('workflow.config.addToOrder') }}</button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.config-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.field-input {
  padding: 8px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-size: 12px;
  resize: vertical;
}

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: -8px 0 0;
}

.empty-hint {
  padding: 12px;
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--bg-primary);
  border: 1px dashed var(--border-subtle);
  border-radius: 6px;
  text-align: center;
}

.ordered-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ordered-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
}

.ordered-item.unlisted {
  opacity: 0.6;
  border-style: dashed;
}

.order-idx {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.order-label {
  flex: 1;
  font-size: 12px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

.order-btn {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 11px;
  cursor: pointer;
}

.order-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.order-btn:not(:disabled):hover {
  background: var(--bg-hover);
}

.order-btn.danger {
  color: #ef4444;
}

.order-btn.add {
  width: auto;
  padding: 0 8px;
  font-size: 11px;
  color: var(--accent);
}
</style>
