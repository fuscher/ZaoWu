<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'
import type { ModelSlot } from '@/types/workflow'
import NumberInput from '@/components/NumberInput.vue'

const props = withDefaults(defineProps<{
  modelValue: ModelSlot
  showMaxTokens?: boolean
  showTemperature?: boolean
}>(), {
  showMaxTokens: true,
  showTemperature: true,
})

const emit = defineEmits<{
  'update:modelValue': [value: ModelSlot]
}>()

const { t } = useI18n()
const chatStore = useChatStore()

const providersLoaded = ref(false)

onMounted(async () => {
  if (chatStore.providers.length === 0) {
    await chatStore.loadProviders()
  }
  providersLoaded.value = true
})

// ── Provider ──────────────────────────────────────────────

const currentProvider = computed(() =>
  chatStore.providers.find((p) => p.id === props.modelValue.providerId),
)

const providerOptions = computed(() =>
  chatStore.providers.map((p) => ({ value: p.id, label: p.name })),
)

function onProviderChange(providerId: string) {
  const provider = chatStore.providers.find((p) => p.id === providerId)
  const firstModelId = provider?.models?.[0]?.id ?? ''
  // provider 切换时自动选择首个模型
  emit('update:modelValue', {
    ...props.modelValue,
    providerId,
    modelId: firstModelId,
  })
}

// ── Model ─────────────────────────────────────────────────

const modelOptions = computed(() =>
  (currentProvider.value?.models ?? []).map((m) => ({
    value: m.id,
    label: m.name || m.id,
  })),
)

const currentModelInfo = computed(() =>
  currentProvider.value?.models?.find((m) => m.id === props.modelValue.modelId),
)

function onModelChange(modelId: string) {
  emit('update:modelValue', { ...props.modelValue, modelId })
}

// provider 变化时若当前 modelId 在新 provider 中不存在，回退到首个
watch(() => props.modelValue.providerId, () => {
  const first = modelOptions.value[0]
  if (first && !modelOptions.value.find((m) => m.value === props.modelValue.modelId)) {
    emit('update:modelValue', {
      ...props.modelValue,
      modelId: first.value,
    })
  }
})

// ── MaxTokens ─────────────────────────────────────────────

const suggestedMaxTokens = computed(() => {
  const ctxLen = currentModelInfo.value?.contextLength
  if (!ctxLen) return 4096
  return Math.floor(ctxLen / 2)
})

const isMaxTokensAuto = computed(() => props.modelValue.maxTokens === undefined)

const effectiveMaxTokens = computed(() =>
  props.modelValue.maxTokens ?? suggestedMaxTokens.value,
)

function onMaxTokensInput(v: number | undefined) {
  emit('update:modelValue', { ...props.modelValue, maxTokens: v })
}

function resetMaxTokens() {
  emit('update:modelValue', { ...props.modelValue, maxTokens: undefined })
}

// ── Temperature ───────────────────────────────────────────

function onTemperatureInput(v: number | undefined) {
  if (v === undefined) return
  emit('update:modelValue', { ...props.modelValue, temperature: v })
}
</script>

<template>
  <div class="model-selector">
    <!-- Empty providers -->
    <div v-if="providersLoaded && chatStore.providers.length === 0" class="no-providers">
      <p class="hint-warning">{{ t('workflow.config.noProvidersHint') }}</p>
    </div>

    <template v-else>
      <!-- Provider -->
      <label class="field-label">{{ t('workflow.config.providerId') }}</label>
      <select
        :value="modelValue.providerId"
        class="field-input"
        @change="onProviderChange(($event.target as HTMLSelectElement).value)"
      >
        <option value="" disabled>{{ t('workflow.config.selectProvider') }}</option>
        <option v-for="opt in providerOptions" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </option>
      </select>

      <!-- Model -->
      <label class="field-label">{{ t('workflow.config.modelId') }}</label>
      <select
        :value="modelValue.modelId"
        class="field-input"
        @change="onModelChange(($event.target as HTMLSelectElement).value)"
      >
        <option value="" disabled>{{ t('workflow.config.selectModel') }}</option>
        <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </option>
      </select>
      <p v-if="modelOptions.length === 0 && modelValue.providerId" class="hint">
        {{ t('workflow.config.noModels') }}
      </p>

      <!-- Temperature -->
      <template v-if="showTemperature">
        <label class="field-label">{{ t('workflow.config.temperature') }}</label>
        <NumberInput
          :model-value="modelValue.temperature ?? 0.7"
          :min="0"
          :max="2"
          :step="0.1"
          variant="input"
          block
          @update:model-value="onTemperatureInput"
        />
      </template>

      <!-- Max Tokens -->
      <template v-if="showMaxTokens">
        <div class="max-tokens-header">
          <label class="field-label">{{ t('workflow.config.maxTokens') }}</label>
          <span v-if="isMaxTokensAuto" class="auto-badge">{{ t('workflow.config.maxTokensAuto') }}</span>
          <button
            v-if="!isMaxTokensAuto"
            class="reset-link"
            @click="resetMaxTokens"
          >
            {{ t('workflow.config.resetAuto') }}
          </button>
        </div>
        <NumberInput
          :model-value="effectiveMaxTokens"
          :placeholder="String(suggestedMaxTokens)"
          :min="1"
          variant="input"
          block
          allow-empty
          :muted="isMaxTokensAuto"
          @update:model-value="onMaxTokensInput"
        />
        <p v-if="isMaxTokensAuto" class="hint">
          {{ t('workflow.config.maxTokensAutoHint', { suggested: suggestedMaxTokens }) }}
        </p>
      </template>
    </template>
  </div>
</template>

<style scoped>
.model-selector {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.no-providers {
  padding: 12px;
  border-radius: 6px;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
}

.hint-warning {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0;
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

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 0;
}

.max-tokens-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.auto-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--accent-muted);
  color: var(--accent);
}

.reset-link {
  border: none;
  background: none;
  color: var(--accent);
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}

.reset-link:hover {
  text-decoration: underline;
}
</style>
