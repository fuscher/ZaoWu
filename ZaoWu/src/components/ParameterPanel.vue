<script setup lang="ts">
import { ref, watch } from 'vue'
import { Settings2, RotateCcw } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'

const chatStore = useChatStore()
const { t } = useI18n()
const isOpen = ref(false)

const temperature = ref(chatStore.config.temperature)
const maxTokens = ref(chatStore.config.maxTokens)
const topP = ref(chatStore.config.topP)
const systemPrompt = ref(chatStore.config.systemPrompt)

watch(
  () => chatStore.config,
  (c) => {
    temperature.value = c.temperature
    maxTokens.value = c.maxTokens
    topP.value = c.topP
    systemPrompt.value = c.systemPrompt
  }
)

function apply() {
  chatStore.updateConfig({
    temperature: temperature.value,
    maxTokens: maxTokens.value,
    topP: topP.value,
    systemPrompt: systemPrompt.value,
  })
  isOpen.value = false
}

function reset() {
  temperature.value = 0.7
  maxTokens.value = 4096
  topP.value = 1.0
  systemPrompt.value = 'You are a helpful assistant.'
  apply()
}
</script>

<template>
  <div class="parameter-panel">
    <button class="panel-trigger" :title="t('chat.parameters')" @click="isOpen = !isOpen">
      <Settings2 :size="14" />
    </button>

    <Transition name="panel">
      <div v-if="isOpen" class="panel-dropdown">
        <div class="panel-header">
          <span class="panel-title">{{ t('chat.parameters') }}</span>
          <button class="reset-btn" :title="t('chat.resetParams')" @click="reset">
            <RotateCcw :size="12" />
          </button>
        </div>

        <div class="param-group">
          <label class="param-label">
            {{ t('chat.systemPrompt') }}
          </label>
          <textarea
            v-model="systemPrompt"
            class="param-textarea"
            rows="3"
            :placeholder="t('chat.systemPromptPlaceholder')"
          />
        </div>

        <div class="param-group">
          <label class="param-label">
            {{ t('chat.temperature') }}
            <span class="param-value">{{ temperature.toFixed(2) }}</span>
          </label>
          <input v-model.number="temperature" type="range" min="0" max="2" step="0.01" class="param-slider" />
        </div>

        <div class="param-group">
          <label class="param-label">
            {{ t('chat.maxTokens') }}
            <span class="param-value">{{ maxTokens }}</span>
          </label>
          <input v-model.number="maxTokens" type="range" min="256" max="16384" step="256" class="param-slider" />
        </div>

        <div class="param-group">
          <label class="param-label">
            {{ t('chat.topP') }}
            <span class="param-value">{{ topP.toFixed(2) }}</span>
          </label>
          <input v-model.number="topP" type="range" min="0" max="1" step="0.01" class="param-slider" />
        </div>

        <button class="apply-btn" @click="apply">{{ t('chat.apply') }}</button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.parameter-panel {
  position: relative;
}

.panel-trigger {
  width: 28px;
  height: 28px;
  border: none;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  transition: all var(--transition);
}

.panel-trigger:hover {
  background: var(--bg-glass-hover);
  color: var(--accent);
}

.panel-dropdown {
  position: absolute;
  bottom: calc(100% + 8px);
  right: 0;
  width: 280px;
  background: var(--bg-primary);
  border: 1px solid var(--border-glass);
  border-radius: 12px;
  padding: 14px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  z-index: 100;
}

.panel-enter-active,
.panel-leave-active {
  transition: all 0.15s ease;
}

.panel-enter-from,
.panel-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.panel-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.reset-btn {
  width: 22px;
  height: 22px;
  border: none;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
}

.reset-btn:hover {
  background: var(--bg-glass);
  color: var(--accent);
}

.param-group {
  margin-bottom: 12px;
}

.param-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.param-value {
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  color: var(--text-tertiary);
  font-size: 11px;
}

.param-slider {
  width: 100%;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--bg-glass);
  border-radius: 2px;
  outline: none;
}

.param-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--accent);
  cursor: pointer;
  border: 2px solid var(--bg-primary);
}

.param-textarea {
  width: 100%;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 8px;
  color: var(--text-primary);
  font-size: 12px;
  font-family: inherit;
  resize: vertical;
  outline: none;
}

.param-textarea::placeholder {
  color: var(--text-tertiary);
}

.param-textarea:focus {
  border-color: var(--accent);
}

.apply-btn {
  width: 100%;
  padding: 6px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: background var(--transition);
}

.apply-btn:hover {
  background: var(--accent-hover);
}
</style>
