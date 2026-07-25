<script setup lang="ts">
import { computed } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import type { WorkflowNode, ModelSlot, PromptSlot } from '@/types/workflow'

const props = defineProps<{
  node: WorkflowNode
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()

const slots = computed(() => props.node.config.slots ?? {})

const model = computed<ModelSlot>({
  get: () =>
    (slots.value.model as ModelSlot) ?? { providerId: '', modelId: '' },
  set: (v) =>
    workflowStore.updateNodeConfig(props.node.id, {
      slots: { ...slots.value, model: v },
    }),
})

const prompt = computed<PromptSlot>({
  get: () =>
    (slots.value.prompt as PromptSlot) ?? { template: '{{input}}', version: 1 },
  set: (v) =>
    workflowStore.updateNodeConfig(props.node.id, {
      slots: { ...slots.value, prompt: v },
    }),
})

function updateModel(patch: Partial<ModelSlot>) {
  model.value = { ...model.value, ...patch }
}

function updatePrompt(patch: Partial<PromptSlot>) {
  prompt.value = { ...prompt.value, ...patch }
}
</script>

<template>
  <div class="config-form">
    <h4 class="section-title">{{ t('workflow.config.model') }}</h4>

    <label class="field-label">{{ t('workflow.config.providerId') }}</label>
    <input
      :value="model.providerId"
      class="field-input"
      type="text"
      @input="updateModel({ providerId: ($event.target as HTMLInputElement).value })"
    />

    <label class="field-label">{{ t('workflow.config.modelId') }}</label>
    <input
      :value="model.modelId"
      class="field-input"
      type="text"
      @input="updateModel({ modelId: ($event.target as HTMLInputElement).value })"
    />

    <label class="field-label">{{ t('workflow.config.temperature') }}</label>
    <input
      :value="model.temperature ?? 0.7"
      class="field-input"
      type="number"
      step="0.1"
      min="0"
      max="2"
      @input="updateModel({ temperature: Number(($event.target as HTMLInputElement).value) })"
    />

    <label class="field-label">{{ t('workflow.config.maxTokens') }}</label>
    <input
      :value="model.maxTokens ?? 4096"
      class="field-input"
      type="number"
      @input="updateModel({ maxTokens: Number(($event.target as HTMLInputElement).value) })"
    />

    <h4 class="section-title">{{ t('workflow.config.prompt') }}</h4>

    <label class="field-label">{{ t('workflow.config.systemPrompt') }}</label>
    <textarea
      :value="prompt.systemPrompt ?? ''"
      class="field-input"
      rows="3"
      @input="updatePrompt({ systemPrompt: ($event.target as HTMLTextAreaElement).value })"
    />

    <label class="field-label">{{ t('workflow.config.template') }}</label>
    <textarea
      :value="prompt.template"
      class="field-input"
      rows="5"
      @input="updatePrompt({ template: ($event.target as HTMLTextAreaElement).value })"
    />
  </div>
</template>

<style scoped>
.config-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-title {
  margin: 8px 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
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
</style>
