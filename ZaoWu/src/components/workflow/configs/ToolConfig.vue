<script setup lang="ts">
import { computed } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import type { WorkflowNode, ToolDef } from '@/types/workflow'
import NumberInput from '@/components/NumberInput.vue'

const props = defineProps<{
  node: WorkflowNode
  tools?: ToolDef[]
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()

const toolName = computed({
  get: () => (props.node.config.toolName as string) ?? '',
  set: (v) => {
    // 切换工具时清空旧参数
    workflowStore.updateNodeConfig(props.node.id, { toolName: v, toolArgs: {} })
  },
})

const selectedTool = computed(() =>
  props.tools?.find((t) => t.name === toolName.value) ?? null,
)

const properties = computed(() =>
  selectedTool.value?.parameters?.properties ?? {},
)

const requiredFields = computed(() =>
  new Set(selectedTool.value?.parameters?.required ?? []),
)

function args(): Record<string, unknown> {
  return (props.node.config.toolArgs as Record<string, unknown>) ?? {}
}

function getArg(key: string): unknown {
  return args()[key]
}

function setArg(key: string, value: unknown) {
  const next = { ...args() }
  if (value === undefined) {
    delete next[key]
  } else {
    next[key] = value
  }
  workflowStore.updateNodeConfig(props.node.id, { toolArgs: next })
}

function setArgJson(key: string, raw: string) {
  const trimmed = raw.trim()
  if (!trimmed) {
    setArg(key, undefined)
    return
  }
  try {
    setArg(key, JSON.parse(trimmed))
  } catch {
    // 用户输入不完整 JSON 时保持原值，等用户继续输入
  }
}

// 原始 JSON 编辑器（高级 fallback）
const toolArgsText = computed({
  get: () => JSON.stringify(args(), null, 2),
  set: (v) => {
    try {
      const parsed = JSON.parse(v)
      workflowStore.updateNodeConfig(props.node.id, { toolArgs: parsed })
    } catch {
      // ignore invalid JSON while typing
    }
  },
})

// 属性类型推断辅助
function fieldType(prop: { type: string; enum?: string[] }): string {
  if (prop.enum) return 'enum'
  return prop.type
}
</script>

<template>
  <div class="config-form">
    <label class="field-label">{{ t('workflow.config.toolName') }}</label>
    <select v-model="toolName" class="field-input">
      <option value="" disabled>{{ t('workflow.config.toolName') }}</option>
      <option
        v-for="t in props.tools ?? []"
        :key="t.name"
        :value="t.name"
      >
        {{ t.name }} — {{ t.description }}
      </option>
    </select>

    <!-- 动态表单字段 -->
    <template v-if="selectedTool">
      <div
        v-for="(prop, key) in properties"
        :key="key"
        class="arg-field"
      >
        <label class="field-label">
          {{ key }}
          <span v-if="requiredFields.has(key)" class="required-mark">*</span>
          <span class="field-type-badge">{{ prop.type }}</span>
        </label>
        <p v-if="prop.description" class="field-hint">{{ prop.description }}</p>

        <!-- string -->
        <input
          v-if="fieldType(prop) === 'string'"
          class="field-input"
          type="text"
          :value="String(getArg(key) ?? '')"
          :placeholder="prop.default != null ? String(prop.default) : key"
          @input="setArg(key, ($event.target as HTMLInputElement).value || undefined)"
        />

        <!-- enum (select) -->
        <select
          v-else-if="fieldType(prop) === 'enum'"
          class="field-input"
          :value="String(getArg(key) ?? '')"
          @change="setArg(key, ($event.target as HTMLSelectElement).value || undefined)"
        >
          <option value="">--</option>
          <option v-for="opt in prop.enum" :key="opt" :value="opt">{{ opt }}</option>
        </select>

        <!-- integer -->
        <NumberInput
          v-else-if="prop.type === 'integer'"
          :model-value="typeof getArg(key) === 'number' ? (getArg(key) as number) : undefined"
          :placeholder="prop.default != null ? String(prop.default) : key"
          :step="1"
          variant="input"
          block
          allow-empty
          @update:model-value="setArg(key, $event)"
        />

        <!-- number -->
        <NumberInput
          v-else-if="prop.type === 'number'"
          :model-value="typeof getArg(key) === 'number' ? (getArg(key) as number) : undefined"
          :placeholder="prop.default != null ? String(prop.default) : key"
          :snap="false"
          variant="input"
          block
          allow-empty
          @update:model-value="setArg(key, $event)"
        />

        <!-- boolean -->
        <label v-else-if="prop.type === 'boolean'" class="checkbox-field">
          <input
            type="checkbox"
            :checked="Boolean(getArg(key))"
            @change="setArg(key, ($event.target as HTMLInputElement).checked)"
          />
          <span class="checkbox-label-text">{{ Boolean(getArg(key)) ? 'true' : 'false' }}</span>
        </label>

        <!-- array / object fallback textarea -->
        <textarea
          v-else
          class="field-input mono"
          rows="3"
          :value="getArg(key) != null ? JSON.stringify(getArg(key)) : ''"
          :placeholder="prop.default != null ? JSON.stringify(prop.default) : `[ ... ]`"
          @input="setArgJson(key, ($event.target as HTMLTextAreaElement).value)"
        />
      </div>

      <!-- Advanced: 原始 JSON -->
      <details class="advanced-section">
        <summary class="advanced-toggle">{{ t('workflow.config.toolArgsAdvanced') }}</summary>
        <textarea v-model="toolArgsText" class="field-input mono" rows="6" />
      </details>
    </template>

    <!-- 没有选中工具时显示原始 JSON 编辑器 -->
    <template v-else>
      <label class="field-label">{{ t('workflow.config.toolArgs') }}</label>
      <textarea v-model="toolArgsText" class="field-input mono" rows="6" />
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
}

.field-input.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.arg-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-type-badge {
  margin-left: 6px;
  padding: 0 4px;
  border-radius: 3px;
  background: var(--bg-primary);
  color: var(--text-tertiary);
  font-size: 10px;
  font-weight: 400;
}

.required-mark {
  color: #ef4444;
  font-weight: 700;
  margin-left: 2px;
}

.field-hint {
  margin: 0;
  font-size: 11px;
  color: var(--text-tertiary);
  line-height: 1.4;
}

.checkbox-field {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  cursor: pointer;
}

.checkbox-label-text {
  font-size: 12px;
  color: var(--text-primary);
}

.advanced-section {
  border-top: 1px solid var(--border-subtle);
  padding-top: 8px;
}

.advanced-toggle {
  font-size: 11px;
  color: var(--text-tertiary);
  cursor: pointer;
  user-select: none;
}

.advanced-toggle:hover {
  color: var(--text-secondary);
}
</style>
