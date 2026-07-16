<script setup lang="ts">
import { ref } from 'vue'
import { Loader, AlertCircle, Check, ChevronRight, X } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { ToolCall, ToolResult } from '@/types'

const props = defineProps<{
  toolCall?: ToolCall
  toolResult?: ToolResult
  isLoading?: boolean
  requiresApproval?: boolean
}>()

const emit = defineEmits<{
  approve: [requestId: string]
  reject: [requestId: string]
}>()

const { t } = useI18n()
const isExpanded = ref(false)
const approved = ref(false)

function toggle() {
  isExpanded.value = !isExpanded.value
}

function approve() {
  approved.value = true
  if (props.toolCall?.requestId) {
    emit('approve', props.toolCall.requestId)
  }
}

function reject() {
  if (props.toolCall?.requestId) {
    emit('reject', props.toolCall.requestId)
  }
}

function iconForTool(name: string): string {
  const map: Record<string, string> = {
    read_file: '📄',
    write_file: '✏️',
    list_files: '📁',
    search_code: '🔍',
    git_status: '📊',
    git_diff: '📋',
    git_log: '📜',
    run_command: '💻',
  }
  return map[name] || '🔧'
}

function summaryForResult(result: ToolResult): string {
  if (!result.content) return ''
  switch (result.tool) {
    case 'read_file':
      return `Read ${result.content.length} chars`
    case 'list_files':
      try {
        const tree = JSON.parse(result.content)
        return `${Array.isArray(tree) ? tree.length : 0} items`
      } catch { return '' }
    case 'search_code':
      try {
        const search = JSON.parse(result.content)
        return `${search.totalMatches || 0} matches in ${search.totalFiles || 0} files`
      } catch { return '' }
    case 'git_status':
      return ''
    case 'git_diff':
      try {
        const lines = result.content.split('\n')
        const added = lines.filter(l => l.startsWith('+') && !l.startsWith('+++')).length
        const removed = lines.filter(l => l.startsWith('-') && !l.startsWith('---')).length
        return `+${added} -${removed} lines`
      } catch { return result.content.slice(0, 80) }
    case 'git_log':
      try {
        const log = JSON.parse(result.content)
        return `${Array.isArray(log) ? log.length : 0} commits`
      } catch { return result.content.slice(0, 80) }
    case 'run_command':
      try {
        const cmd = JSON.parse(result.content)
        return `Exit code: ${cmd.exitCode ?? 0}`
      } catch { return 'Exit code: ?' }
    default:
      return result.content.slice(0, 80)
  }
}
</script>

<template>
  <div class="tool-call-card" :class="{
    expanded: isExpanded,
    error: toolResult?.success === false,
    pending: requiresApproval && !approved,
  }">
    <div class="tool-call-header" @click="toggle">
      <span class="tool-icon">{{ iconForTool(toolResult?.tool || toolCall?.name || 'unknown') }}</span>
      <span class="tool-name">{{ toolCall?.name || toolResult?.tool }}</span>
      <span v-if="toolResult && !isExpanded" class="tool-summary">
        {{ toolResult.success ? summaryForResult(toolResult) : toolResult.error }}
      </span>
      <span class="tool-status">
        <template v-if="isLoading">
          <Loader :size="14" class="spinning" />
        </template>
        <template v-else-if="requiresApproval && !approved">
          <span class="approval-badge">{{ t('agent.requiresApproval') }}</span>
        </template>
        <template v-else-if="toolResult?.success === false">
          <AlertCircle :size="14" class="text-error" />
        </template>
        <template v-else-if="toolResult?.success">
          <Check :size="14" class="text-success" />
        </template>
      </span>
      <ChevronRight :size="14" class="expand-arrow" :class="{ rotated: isExpanded }" />
    </div>

    <div v-if="isExpanded" class="tool-call-body">
      <div v-if="toolCall" class="tool-section">
        <div class="section-label">{{ t('agent.parameters') }}</div>
        <pre class="tool-json"><code>{{ JSON.stringify(toolCall.arguments, null, 2) }}</code></pre>
      </div>
      <div v-if="toolResult" class="tool-section">
        <div class="section-label">{{ toolResult.success ? t('agent.result') : t('agent.error') }}</div>
        <pre class="tool-content" :class="{ 'error-text': !toolResult.success }"><code>{{ toolResult.content || toolResult.error }}</code></pre>
      </div>
      <!-- Phase 2: user confirmation buttons -->
      <div v-if="requiresApproval && !approved" class="tool-actions">
        <button class="btn-approve" @click.stop="approve">
          <Check :size="14" /> {{ t('agent.approve') }}
        </button>
        <button class="btn-reject" @click.stop="reject">
          <X :size="14" /> {{ t('agent.reject') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-call-card {
  margin: 6px 0;
  border-radius: 10px;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  overflow: hidden;
  transition: border-color var(--transition), box-shadow var(--transition);
}

.tool-call-card.expanded {
  border-color: var(--accent-muted);
  box-shadow: 0 2px 8px var(--shadow);
}

.tool-call-card.error {
  border-color: var(--danger);
}

.tool-call-card.error .tool-call-header {
  background: rgba(201, 42, 42, 0.06);
}

[data-theme='light'] .tool-call-card.error .tool-call-header {
  background: rgba(201, 42, 42, 0.06);
}

.tool-call-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  transition: background var(--transition);
  min-width: 0;
}

.tool-call-header:hover {
  background: var(--bg-secondary);
}

.tool-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.tool-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  flex-shrink: 0;
}

.tool-summary {
  font-size: 11.5px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

.tool-status {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.text-error {
  color: var(--danger);
}

.text-success {
  color: var(--success);
}

.approval-badge {
  font-size: 10.5px;
  font-weight: 600;
  color: var(--warning);
  background: rgba(255, 149, 0, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
}

.expand-arrow {
  color: var(--text-tertiary);
  transition: transform var(--transition);
  flex-shrink: 0;
}

.expand-arrow.rotated {
  transform: rotate(90deg);
}

.tool-call-body {
  border-top: 1px solid var(--border-subtle);
  padding: 10px 12px;
}

.tool-section {
  margin-bottom: 10px;
}

.tool-section:last-child {
  margin-bottom: 0;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.tool-json,
.tool-content {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 8px 10px;
  overflow-x: auto;
  font-size: 12px;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  color: var(--text-primary);
  max-height: 240px;
  overflow-y: auto;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.tool-content.error-text {
  color: var(--danger);
  border-color: rgba(201, 42, 42, 0.2);
}

.tool-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle);
}

.btn-approve,
.btn-reject {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  border-radius: 6px;
  border: none;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition);
}

.btn-approve {
  background: var(--success);
  color: #fff;
}

.btn-approve:hover {
  filter: brightness(0.88);
}

.btn-reject {
  background: var(--danger);
  color: #fff;
}

.btn-reject:hover {
  filter: brightness(0.88);
}
</style>
