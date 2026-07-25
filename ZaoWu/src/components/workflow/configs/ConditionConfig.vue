<script setup lang="ts">
import { computed } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import type { WorkflowNode, ConditionConfig as ConditionConfigType, ConditionRule } from '@/types/workflow'

const props = defineProps<{
  node: WorkflowNode
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()

const cfg = computed<ConditionConfigType>({
  get: () =>
    (props.node.config.conditionConfig as ConditionConfigType) ?? {
      mode: 'simple',
      rules: [],
      defaultBranch: 'false',
    },
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { conditionConfig: v }),
})

const modeOptions = [
  { value: 'simple', label: t('workflow.config.simpleMode') },
  { value: 'code', label: t('workflow.config.codeMode') },
]

function update(patch: Partial<ConditionConfigType>) {
  cfg.value = { ...cfg.value, ...patch }
}

function addRule() {
  const rules = [...(cfg.value.rules ?? []), { operator: 'eq', value: '', branch: 'true' } as ConditionRule]
  update({ rules })
}

function removeRule(index: number) {
  const rules = [...(cfg.value.rules ?? [])]
  rules.splice(index, 1)
  update({ rules })
}

function updateRule(index: number, patch: Partial<ConditionRule>) {
  const rules = [...(cfg.value.rules ?? [])]
  rules[index] = { ...rules[index], ...patch } as ConditionRule
  update({ rules })
}
</script>

<template>
  <div class="config-form">
    <label class="field-label">{{ t('workflow.config.judgeMode') }}</label>
    <select :value="cfg.mode" class="field-input" @change="update({ mode: ($event.target as HTMLSelectElement).value as any })">
      <option v-for="opt in modeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
    </select>

    <template v-if="cfg.mode === 'code'">
      <label class="field-label">{{ t('workflow.config.expression') }}</label>
      <textarea
        :value="cfg.expression ?? 'True'"
        class="field-input mono"
        rows="3"
        @input="update({ expression: ($event.target as HTMLTextAreaElement).value })"
      />
      <p class="hint">{{ t('workflow.config.expressionHint') }}</p>
    </template>

    <template v-else>
      <div class="rules-header">
        <label class="field-label">{{ t('workflow.config.rules') }}</label>
        <button class="icon-btn" @click="addRule">+</button>
      </div>
      <div v-for="(rule, idx) in cfg.rules ?? []" :key="idx" class="rule-row">
        <select :value="rule.operator" class="field-input small" @change="updateRule(idx, { operator: ($event.target as HTMLSelectElement).value as any })">
          <option value="eq">=</option>
          <option value="ne">!=</option>
          <option value="gt">&gt;</option>
          <option value="gte">&gt;=</option>
          <option value="lt">&lt;</option>
          <option value="lte">&lt;=</option>
          <option value="contains">contains</option>
          <option value="regex">regex</option>
        </select>
        <input
          :value="rule.value"
          class="field-input small"
          type="text"
          :placeholder="t('workflow.config.value')"
          @input="updateRule(idx, { value: ($event.target as HTMLInputElement).value })"
        />
        <select :value="rule.branch ?? 'true'" class="field-input small" @change="updateRule(idx, { branch: ($event.target as HTMLSelectElement).value })">
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
        <button class="icon-btn danger" @click="removeRule(idx)">×</button>
      </div>
    </template>

    <label class="field-label">{{ t('workflow.config.defaultBranch') }}</label>
    <select :value="cfg.defaultBranch ?? 'false'" class="field-input" @change="update({ defaultBranch: ($event.target as HTMLSelectElement).value })">
      <option value="true">true</option>
      <option value="false">false</option>
    </select>
  </div>
</template>

<style scoped>
.config-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
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
}

.field-input.small {
  padding: 6px;
  font-size: 11px;
}

.field-input.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 0;
}

.rules-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.rule-row {
  display: grid;
  grid-template-columns: 70px 1fr 70px 24px;
  gap: 6px;
  align-items: center;
}

.icon-btn {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  cursor: pointer;
}

.icon-btn.danger {
  color: #ef4444;
}
</style>
