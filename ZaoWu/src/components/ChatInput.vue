<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Send, Square, Bot, Sparkles } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'
import ModelSwitcher from './ModelSwitcher.vue'
import ParameterPanel from './ParameterPanel.vue'

const chatStore = useChatStore()
const { t } = useI18n()
const input = ref('')
const isComposing = ref(false)

function handleSend() {
  if (!input.value.trim() || isComposing.value) return
  if (chatStore.agentMode) {
    chatStore.sendAgentMessage(input.value.trim())
  } else {
    chatStore.sendMessage(input.value.trim())
  }
  input.value = ''
}

function handleStop() {
  chatStore.stopStreaming()
}

async function toggleAgentMode() {
  if (!chatStore.currentConversation) {
    await chatStore.createNewConversation()
  }
  chatStore.agentMode = !chatStore.agentMode
}

onMounted(() => {
  chatStore.loadSkills()
})

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="chat-input">
    <div class="input-wrapper">
      <textarea
        v-model="input"
        :placeholder="t('chat.placeholder')"
        rows="1"
        @keydown="handleKeydown"
        @compositionstart="isComposing = true"
        @compositionend="isComposing = false"
        @input="isComposing = false"
      />
      <button
        v-if="chatStore.isStreaming"
        class="stop-btn"
        :title="t('chat.stopGeneration')"
        @click="handleStop"
      >
        <Square :size="14" />
      </button>
      <button v-else class="send-btn" :class="{ active: input.trim() }" @click="handleSend">
        <Send :size="16" />
      </button>
    </div>
    <div class="input-footer">
      <div class="footer-left">
        <ModelSwitcher />
        <ParameterPanel />
        <button
          class="agent-toggle"
          :class="{ active: chatStore.agentMode }"
          :title="chatStore.agentMode ? t('agent.agentModeDesc') : t('agent.agentMode')"
          @click="toggleAgentMode"
        >
          <Bot :size="14" />
          <span>{{ t('agent.agentMode') }}</span>
        </button>

        <select
          v-if="chatStore.agentMode"
          v-model="chatStore.selectedSkill"
          class="skill-select"
          :title="t('agent.skill')"
        >
          <option value="">{{ t('agent.noSkill') }}</option>
          <option
            v-for="skill in chatStore.availableSkills.filter((s) => s.enabled)"
            :key="skill.name"
            :value="skill.name"
            :title="skill.description || skill.name"
          >
            {{ skill.name }}
          </option>
        </select>
      </div>
      <span class="hint">
        {{
          chatStore.isStreaming
            ? t('agent.agentThinking')
            : chatStore.agentMode
              ? t('agent.agentModeActive')
              : t('chat.shortcutHint')
        }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.chat-input {
  padding: 12px 16px;
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.input-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 14px;
  padding: 8px 8px 8px 16px;
  transition: border-color var(--transition);
}

.input-wrapper:focus-within {
  border-color: var(--accent);
}

textarea {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-size: 13.5px;
  font-family: inherit;
  resize: none;
  line-height: 1.5;
  max-height: 120px;
}

textarea::placeholder {
  color: var(--text-tertiary);
}

.send-btn {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  border: none;
  background: var(--bg-glass);
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition);
}

.send-btn.active {
  background: var(--accent);
  color: #fff;
}

.send-btn.active:hover {
  background: var(--accent-hover);
}

.stop-btn {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  border: none;
  background: var(--danger);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition);
  animation: pulse-red 1.5s infinite;
}

.stop-btn:hover {
  background: var(--danger);
  filter: brightness(0.88);
}

@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 0 rgba(201, 42, 42, 0.4); }
  50% { box-shadow: 0 0 0 4px rgba(201, 42, 42, 0); }
}

.input-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 4px;
}

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
}

.agent-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  color: var(--text-tertiary);
  font-size: 11.5px;
  cursor: pointer;
  transition: all var(--transition);
  white-space: nowrap;
}

.agent-toggle:hover {
  border-color: var(--accent-muted);
  color: var(--text-secondary);
}

.agent-toggle.active {
  border-color: var(--accent);
  background: var(--accent-muted);
  color: var(--accent);
}

.agent-toggle.active:hover {
  background: var(--accent);
  color: #fff;
}

.skill-select {
  appearance: none;
  -webkit-appearance: none;
  padding: 4px 24px 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background:
    linear-gradient(45deg, transparent 50%, var(--text-tertiary) 50%),
    linear-gradient(135deg, var(--text-tertiary) 50%, transparent 50%),
    var(--bg-secondary);
  background-position: right 10px center, right 6px center, 0 0;
  background-size: 4px 4px, 4px 4px, 100% 100%;
  background-repeat: no-repeat;
  color: var(--text-secondary);
  font-size: 11.5px;
  cursor: pointer;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-select:hover {
  border-color: var(--border-glass);
}

.skill-select:focus {
  outline: none;
  border-color: var(--accent);
}
</style>
