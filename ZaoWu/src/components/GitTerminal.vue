<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'

const { t } = useI18n()
const gitStore = useGitStore()
const command = ref('')
const output = ref<string[]>([])
const history = ref<string[]>([])
const historyIndex = ref(-1)
const outputContainer = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)

async function exec() {
  const cmd = command.value.trim()
  if (!cmd) return

  command.value = ''
  history.value.unshift(cmd)
  historyIndex.value = -1
  output.value.push('> ' + cmd)

  const result = await gitStore.execTerminalCmd(cmd)
  output.value.push(result || '(no output)')

  await nextTick()
  if (outputContainer.value) {
    outputContainer.value.scrollTop = outputContainer.value.scrollHeight
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    exec()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (history.value.length > 0 && historyIndex.value < history.value.length - 1) {
      historyIndex.value++
      command.value = history.value[historyIndex.value] || ''
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (historyIndex.value > 0) {
      historyIndex.value--
      command.value = history.value[historyIndex.value] || ''
    } else {
      historyIndex.value = -1
      command.value = ''
    }
  }
}

function focusInput() {
  inputRef.value?.focus()
}
</script>

<template>
  <div class="terminal" @click="focusInput">
    <div class="terminal-header">
      <span class="terminal-title">{{ t('git.terminal') }}</span>
      <span class="terminal-cwd">{{ gitStore.terminalCwd || t('git.terminalPlaceholder') }}</span>
    </div>
    <div ref="outputContainer" class="terminal-output">
      <div v-if="output.length === 0" class="terminal-placeholder">
        {{ gitStore.selectedProject ? t('git.commandPlaceholder') : t('git.terminalPlaceholder') }}
      </div>
      <div v-for="(line, i) in output" :key="i" class="terminal-line" :class="{ command: line.startsWith('> ') }">
        {{ line }}
      </div>
    </div>
    <div class="terminal-input-line">
      <span class="terminal-prompt">></span>
      <input
        ref="inputRef"
        v-model="command"
        class="terminal-input"
        :placeholder="gitStore.selectedProject ? '' : t('git.terminalPlaceholder')"
        :disabled="!gitStore.selectedProject"
        @keydown="handleKeydown"
      />
    </div>
  </div>
</template>

<style scoped>
.terminal {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-tertiary);
  border-top: 1px solid var(--border-glass);
}

.terminal-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.terminal-title {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.terminal-cwd {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.terminal-output {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.5;
}

.terminal-placeholder {
  color: var(--text-tertiary);
  font-family: inherit;
}

.terminal-line {
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-all;
}

.terminal-line.command {
  color: var(--accent);
}

.terminal-input-line {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.terminal-prompt {
  color: var(--accent);
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
}

.terminal-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
}

.terminal-input:disabled {
  opacity: 0.4;
}
</style>
