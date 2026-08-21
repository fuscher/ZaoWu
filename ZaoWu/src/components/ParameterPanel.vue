<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { Settings2, RotateCcw } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'

const chatStore = useChatStore()
const { t } = useI18n()
const isOpen = ref(false)

const temperature = ref(chatStore.config.temperature)
const maxTokens = ref(chatStore.config.maxTokens)
const maxTokensAuto = ref(chatStore.config.maxTokensAuto ?? true)
const maxGenerationTokens = ref(chatStore.config.maxGenerationTokens ?? 4096)
const topP = ref(chatStore.config.topP)
const systemPrompt = ref(chatStore.config.systemPrompt)

watch(
  () => chatStore.config,
  (c) => {
    temperature.value = c.temperature
    maxTokens.value = c.maxTokens
    maxTokensAuto.value = c.maxTokensAuto ?? true
    maxGenerationTokens.value = c.maxGenerationTokens ?? 4096
    topP.value = c.topP
    systemPrompt.value = c.systemPrompt
  }
)

// 自动模式取值：当前会话模型声明的上下文长度；
// 取不到（供应商不提供）时回退 128K——现代模型上下文普遍 ≥128K，
// 避免小默认值导致长对话频繁触发压缩；超窗时仍有被动 overflow 兜底。
const AUTO_FALLBACK = 131072
const autoMaxTokens = computed(() => {
  const conv = chatStore.currentConversation
  if (!conv) return AUTO_FALLBACK
  const provider = chatStore.providers.find((p) => p.id === conv.providerId)
  const model = provider?.models?.find((m) => m.id === conv.modelId)
  return model?.contextLength ?? AUTO_FALLBACK
})

function onMaxTokensInput(e: Event) {
  if (maxTokensAuto.value) return
  maxTokens.value = Number((e.target as HTMLInputElement).value)
}

function onAutoToggle(v: boolean) {
  maxTokensAuto.value = v
  if (!v) {
    // 切到手动：以模型自动值为起点
    maxTokens.value = autoMaxTokens.value
  }
}

function apply() {
  chatStore.updateConfig({
    temperature: temperature.value,
    maxTokens: maxTokens.value,
    maxTokensAuto: maxTokensAuto.value,
    contextBudget: maxTokens.value,
    maxGenerationTokens: maxGenerationTokens.value,
    topP: topP.value,
    systemPrompt: systemPrompt.value,
  })
  isOpen.value = false
}

function reset() {
  temperature.value = 0.7
  maxTokens.value = 4096
  maxTokensAuto.value = true
  maxGenerationTokens.value = 4096
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
            <span v-if="maxTokensAuto" class="auto-badge">{{ t('chat.maxTokensAuto') }}</span>
            <span v-else class="param-value">{{ maxTokens }}</span>
          </label>
          <label class="param-auto-row">
            <input type="checkbox" :checked="maxTokensAuto" @change="onAutoToggle(($event.target as HTMLInputElement).checked)" />
            <span class="param-auto-label">{{ t('chat.maxTokensAutoLabel') }}</span>
          </label>
          <input
            :value="maxTokensAuto ? autoMaxTokens : maxTokens"
            type="range"
            min="256"
            max="1000000"
            step="256"
            class="param-slider"
            :disabled="maxTokensAuto"
            @input="onMaxTokensInput"
          />
          <p v-if="maxTokensAuto" class="param-hint">
            {{ t('chat.maxTokensAutoHint', { suggested: autoMaxTokens }) }}
          </p>
        </div>

        <div class="param-group">
          <label class="param-label">
            {{ t('chat.maxGenerationTokens') || '生成上限' }}
            <span class="param-value">{{ maxGenerationTokens }}</span>
          </label>
          <input
            v-model.number="maxGenerationTokens"
            type="range"
            min="256"
            max="131072"
            step="256"
            class="param-slider"
          />
          <p class="param-hint">
            {{ t('chat.maxGenerationTokensHint') || 'LLM 单次生成最大 token 数（不影响上下文预算）' }}
          </p>
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

.auto-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--accent-muted);
  color: var(--accent);
}

.param-auto-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  cursor: pointer;
}

.param-auto-label {
  font-size: 11px;
  color: var(--text-tertiary);
}

.param-hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 6px 0 0;
}

.param-slider:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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
  border: 2px solid var(--border-subtle);
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
