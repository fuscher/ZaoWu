<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { Send, Square, Bot, Sparkles, Hammer, ClipboardList } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'
import ModelSwitcher from './ModelSwitcher.vue'
import ParameterPanel from './ParameterPanel.vue'

const chatStore = useChatStore()
const { t } = useI18n()
const input = ref('')
const isComposing = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

// 自适应高度：从单行起随内容增长，最高 160px，超出则内部滚动
function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

function handleSend() {
  if (!input.value.trim() || isComposing.value) return
  if (chatStore.agentMode) {
    chatStore.sendAgentMessage(input.value.trim())
  } else {
    chatStore.sendMessage(input.value.trim())
  }
  input.value = ''
  nextTick(autoResize) // 发送清空后重置回单行高度
}

function onInput() {
  isComposing.value = false
  autoResize()
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

// 技能改为「全部启用即生效」：仅展示当前已启用技能数量，设置模块启用的技能对所有对话生效
const enabledSkillsCount = computed(() =>
  chatStore.availableSkills.filter((s) => s.enabled).length
)

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
        ref="textareaRef"
        v-model="input"
        :placeholder="t('chat.placeholder')"
        rows="1"
        @keydown="handleKeydown"
        @compositionstart="isComposing = true"
        @compositionend="isComposing = false"
        @input="onInput"
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

        <span
          v-if="chatStore.agentMode"
          class="skill-indicator"
          :title="t('agent.skillsEnabledHint')"
        >
          <Sparkles :size="14" />
          <span>{{ enabledSkillsCount }} {{ t('agent.skillsUnit') }}</span>
        </span>

        <!-- 6.3.1: 预设模式切换 — build=全工具可写；plan=只读规划（写工具被 deny） -->
        <div
          v-if="chatStore.agentMode"
          class="preset-switcher"
          :title="t('agent.presetModeDesc')"
        >
          <button
            type="button"
            class="preset-btn"
            :class="{ active: chatStore.preset === 'build' }"
            @click="chatStore.preset = 'build'"
          >
            <Hammer :size="13" />
            {{ t('agent.presetModeBuild') }}
          </button>
          <button
            type="button"
            class="preset-btn"
            :class="{ active: chatStore.preset === 'plan' }"
            @click="chatStore.preset = 'plan'"
          >
            <ClipboardList :size="13" />
            {{ t('agent.presetModePlan') }}
          </button>
        </div>
        <!-- F04: 自动批准写入文件开关 — 仅 write_file 受影响，run_command 仍需确认 -->
        <!-- plan 模式下写工具被 deny，autoApproveWrites 无意义，禁用并提示 -->
        <label
          v-if="chatStore.agentMode"
          class="auto-approve-toggle"
          :class="{ disabled: chatStore.preset === 'plan' }"
          :title="chatStore.preset === 'plan' ? t('agent.presetModePlanAutoApproveDisabled') : t('agent.autoApproveWritesDesc')"
        >
          <input
            type="checkbox"
            v-model="chatStore.autoApproveWrites"
            :disabled="chatStore.preset === 'plan'"
          />
          <span class="toggle-track"><span class="toggle-thumb" /></span>
          <span class="toggle-label">{{ t('agent.autoApproveWrites') }}</span>
        </label>
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
  max-height: 160px;
  overflow-y: auto;
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

.skill-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  color: var(--text-tertiary);
  font-size: 11.5px;
  white-space: nowrap;
}

/* 6.3.1: 预设模式切换器 — 分段按钮 */
.preset-switcher {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: 6px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.preset-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  font-size: 11.5px;
  cursor: pointer;
  transition: background var(--transition), color var(--transition);
  white-space: nowrap;
  flex-shrink: 0;
}

.preset-btn:hover {
  color: var(--text-secondary);
}

.preset-btn.active {
  background: var(--accent-muted);
  color: var(--accent);
}

/* F04: 自动批准写入开关 — 与项目统一 toggle-slider 风格保持一致 */
.auto-approve-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}

.auto-approve-toggle input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-track {
  position: relative;
  width: 28px;
  height: 16px;
  border-radius: 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  transition: background var(--transition), border-color var(--transition);
  flex-shrink: 0;
}

.toggle-thumb {
  position: absolute;
  top: 1px;
  left: 1px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--text-tertiary);
  transition: transform var(--transition), background var(--transition);
}

.auto-approve-toggle input:checked + .toggle-track {
  background: var(--accent-muted);
  border-color: var(--accent);
}

.auto-approve-toggle input:checked + .toggle-track .toggle-thumb {
  transform: translateX(12px);
  background: var(--accent);
}

.toggle-label {
  font-size: 11.5px;
  color: var(--text-tertiary);
  transition: color var(--transition);
}

.auto-approve-toggle:hover .toggle-label {
  color: var(--text-secondary);
}

.auto-approve-toggle input:checked ~ .toggle-label {
  color: var(--accent);
}

/* 6.3.1: plan 模式下 autoApproveWrites 无意义，禁用并降低不透明度 */
.auto-approve-toggle.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.auto-approve-toggle.disabled:hover .toggle-label {
  color: var(--text-tertiary);
}
</style>
