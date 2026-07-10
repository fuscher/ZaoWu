<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Minus, Plus } from '@lucide/vue'

const props = withDefaults(defineProps<{
  modelValue: number
  min?: number
  max?: number
  step?: number
  unit?: string
  placeholder?: string
  variant?: 'stepper' | 'input'
  disabled?: boolean
}>(), {
  min: 1,
  max: 100,
  step: 1,
  unit: '',
  placeholder: '',
  variant: 'stepper',
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: number]
  change: [value: number]
}>()

const rawInput = ref(String(props.modelValue))
const isFocused = ref(false)
const hasError = ref(false)

function clampToStep(value: number): number {
  const stepped = Math.round(value / props.step) * props.step
  return Math.max(props.min, Math.min(props.max, stepped))
}

const displayValue = computed(() => clampToStep(props.modelValue))

watch(() => props.modelValue, (val) => {
  if (!isFocused.value) {
    rawInput.value = String(clampToStep(val))
    hasError.value = false
  }
})

function commitValue(value: number) {
  const clamped = clampToStep(value)
  emit('update:modelValue', clamped)
  emit('change', clamped)
}

function handleDecrease() {
  if (props.disabled) return
  commitValue(props.modelValue - props.step)
}

function handleIncrease() {
  if (props.disabled) return
  commitValue(props.modelValue + props.step)
}

function handleInput(event: Event) {
  const target = event.target as HTMLInputElement
  rawInput.value = target.value
  const parsed = Number(target.value)
  if (!target.value.trim() || isNaN(parsed) || !isFinite(parsed)) {
    hasError.value = true
    return
  }
  hasError.value = false
  commitValue(parsed)
}

function handleBlur() {
  isFocused.value = false
  const parsed = Number(rawInput.value)
  if (hasError.value || rawInput.value.trim() === '' || isNaN(parsed) || !isFinite(parsed)) {
    rawInput.value = String(displayValue.value)
    hasError.value = false
  } else {
    const clamped = clampToStep(parsed)
    rawInput.value = String(clamped)
    commitValue(clamped)
  }
}

function handleFocus() {
  isFocused.value = true
  rawInput.value = String(props.modelValue)
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    handleIncrease()
  } else if (event.key === 'ArrowDown') {
    event.preventDefault()
    handleDecrease()
  } else if (event.key === 'Enter') {
    event.preventDefault()
    ;(event.target as HTMLInputElement).blur()
  }
}
</script>

<template>
  <div class="number-input" :class="[`variant-${variant}`, { disabled, focused: isFocused, error: hasError }]">
    <template v-if="variant === 'stepper'">
      <button class="stepper-btn decrease" :disabled="disabled || modelValue <= min" @click="handleDecrease">
        <Minus :size="12" />
      </button>
      <div class="stepper-display">
        <span class="stepper-value">{{ displayValue }}</span>
        <span v-if="unit" class="stepper-unit">{{ unit }}</span>
      </div>
      <button class="stepper-btn increase" :disabled="disabled || modelValue >= max" @click="handleIncrease">
        <Plus :size="12" />
      </button>
    </template>

    <template v-else>
      <input
        type="text"
        inputmode="numeric"
        :value="rawInput"
        :placeholder="placeholder"
        :disabled="disabled"
        class="plain-input"
        @input="handleInput"
        @blur="handleBlur"
        @focus="handleFocus"
        @keydown="handleKeydown"
      />
      <span v-if="unit" class="input-unit">{{ unit }}</span>
    </template>
  </div>
</template>

<style scoped>
.number-input {
  display: inline-flex;
  align-items: center;
  gap: 0;
  border-radius: 8px;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  transition: all var(--transition);
}

.number-input:hover:not(.disabled) {
  border-color: var(--border-subtle);
}

.number-input.focused {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-muted);
}

.number-input.error {
  border-color: var(--danger);
  box-shadow: 0 0 0 3px rgba(255, 95, 86, 0.12);
}

.number-input.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.variant-stepper {
  padding: 0;
  overflow: hidden;
}

.stepper-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition);
  flex-shrink: 0;
}

.stepper-btn:hover:not(:disabled) {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

.stepper-btn:active:not(:disabled) {
  background: var(--bg-glass-active);
}

.stepper-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.stepper-display {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 0 12px;
  min-width: 50px;
  height: 32px;
}

.stepper-value {
  font-size: 14px;
  font-weight: 600;
  line-height: 1;
  color: var(--text-primary);
  font-family: 'Cascadia Code', 'Fira Code', monospace;
}

.stepper-unit {
  font-size: 11px;
  line-height: 1;
  color: var(--text-tertiary);
}

.variant-input {
  padding: 0;
  gap: 4px;
  padding-right: 8px;
}

.plain-input {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 14px;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  padding: 7px 10px;
  outline: none;
  text-align: right;
  min-width: 60px;
}

.plain-input::placeholder {
  color: var(--text-tertiary);
}

.input-unit {
  font-size: 11px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .stepper-btn {
    width: 28px;
    height: 28px;
  }

  .stepper-display {
    min-width: 40px;
    height: 28px;
    padding: 0 8px;
  }

  .stepper-value {
    font-size: 13px;
  }

  .plain-input {
    font-size: 13px;
    padding: 5px 8px;
    min-width: 45px;
  }
}
</style>
