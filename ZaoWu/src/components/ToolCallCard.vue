<script setup lang="ts">
import { computed, ref } from 'vue'
import { Loader, AlertCircle, Check, ChevronRight, X, Ban, Clock } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { ToolCall, ToolResult, ToolPartState } from '@/types'

const props = defineProps<{
  toolCall?: ToolCall
  toolResult?: ToolResult
  isLoading?: boolean
  requiresApproval?: boolean
  /** 阶段 C6: 生命周期状态（消费 tool_part 事件） */
  part?: ToolPartState
}>()

const emit = defineEmits<{
  approve: [requestId: string, scope: 'once' | 'always']
  reject: [requestId: string, feedback?: string]
}>()

const { t } = useI18n()
const isExpanded = ref(false)
const approved = ref(false)
// 6.3.2: 三态确认 — reject 展开原因输入框
const rejecting = ref(false)
const rejectFeedback = ref('')

/** 阶段 C6: 展示态 = part 状态机优先，回退到 props 推断（历史消息无 part） */
const displayState = computed<{
  key: 'loading' | 'permission' | 'success' | 'failed' | 'denied'
  reason?: string
}>(() => {
  if (props.part) {
    switch (props.part.part) {
      case 'generating':
      case 'running':
        return { key: 'loading' }
      case 'permission_pending':
        return { key: 'permission' }
      case 'success':
        return { key: 'success' }
      case 'denied':
        return { key: 'denied', reason: props.part.reason }
      case 'failed':
        return { key: 'failed', reason: props.part.reason }
    }
  }
  // 历史消息回退：从 toolResult.success 推断
  if (props.toolResult) {
    return props.toolResult.success ? { key: 'success' } : { key: 'failed' }
  }
  return { key: 'loading' }
})

/** denied + plan_mode_readonly → 信息性"被约束"（黄），非错误 */
const isPlanConstrained = computed(
  () => displayState.value.key === 'denied' && displayState.value.reason === 'plan_mode_readonly'
)

function deniedReasonText(reason: string | undefined): string {
  switch (reason) {
    case 'plan_mode_readonly': return t('agent.toolPart.denied.planMode')
    case 'preset_deny': return t('agent.toolPart.denied.preset')
    case 'user_rejected': return t('agent.toolPart.denied.rejected')
    case 'user_stopped':
    case 'timeout': return t('agent.toolPart.denied.timeout')
    default: return t('agent.toolPart.denied.rejected')
  }
}

function toggle() {
  isExpanded.value = !isExpanded.value
}

function approve(scope: 'once' | 'always') {
  approved.value = true
  if (props.toolCall?.requestId) {
    emit('approve', props.toolCall.requestId, scope)
  }
}

function startReject() {
  rejecting.value = true
}

function cancelReject() {
  rejecting.value = false
  rejectFeedback.value = ''
}

function confirmReject() {
  approved.value = true // 隐藏确认按钮（已响应）
  if (props.toolCall?.requestId) {
    emit('reject', props.toolCall.requestId, rejectFeedback.value.trim() || undefined)
  }
  rejecting.value = false
  rejectFeedback.value = ''
}

function iconForTool(name: string): string {
  const map: Record<string, string> = {
    read_file: '📄',
    write_file: '✏️',
    edit_file: '✂️',
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
    case 'write_file':
    case 'edit_file':
      try {
        const r = JSON.parse(result.content)
        if (r.replacements != null) {
          const key = r.replacements === 1 ? 'agent.summary.replacement' : 'agent.summary.replacements'
          return t(key, { n: r.replacements })
        }
        return r.created ? t('agent.summary.created') : t('agent.summary.written')
      } catch { return result.content.slice(0, 80) }
    case 'read_file':
      return t('agent.summary.readChars', { n: result.content.length })
    case 'list_files':
      try {
        const tree = JSON.parse(result.content)
        return t('agent.summary.items', { n: Array.isArray(tree) ? tree.length : 0 })
      } catch { return '' }
    case 'search_code':
      try {
        const search = JSON.parse(result.content)
        return t('agent.summary.matches', { n: search.totalMatches || 0, files: search.totalFiles || 0 })
      } catch { return '' }
    case 'git_status':
      return ''
    case 'git_diff':
      try {
        const lines = result.content.split('\n')
        const added = lines.filter(l => l.startsWith('+') && !l.startsWith('+++')).length
        const removed = lines.filter(l => l.startsWith('-') && !l.startsWith('---')).length
        return t('agent.summary.diffLines', { added, removed })
      } catch { return result.content.slice(0, 80) }
    case 'git_log':
      try {
        const log = JSON.parse(result.content)
        return t('agent.summary.commits', { n: Array.isArray(log) ? log.length : 0 })
      } catch { return result.content.slice(0, 80) }
    case 'run_command':
      try {
        const cmd = JSON.parse(result.content)
        return t('agent.summary.exitCode', { code: cmd.exitCode ?? 0 })
      } catch { return t('agent.summary.exitCodeUnknown') }
    default:
      return result.content.slice(0, 80)
  }
}
</script>

<template>
  <div class="tool-call-card" :class="{
    expanded: isExpanded,
    error: displayState.key === 'failed',
    constrained: isPlanConstrained,
    pending: requiresApproval && !approved,
  }">
    <div class="tool-call-header" @click="toggle">
      <span class="tool-icon">{{ iconForTool(toolResult?.tool || toolCall?.name || 'unknown') }}</span>
      <span class="tool-name">{{ toolCall?.name || toolResult?.tool }}</span>
      <span v-if="toolResult && !isExpanded" class="tool-summary">
        {{ toolResult.success ? summaryForResult(toolResult) : toolResult.error }}
      </span>
      <span v-else-if="isPlanConstrained && !isExpanded" class="tool-summary constrained-summary">
        {{ deniedReasonText(displayState.reason) }}
      </span>
      <span class="tool-status">
        <template v-if="displayState.key === 'loading'">
          <Loader :size="14" class="spinning" />
        </template>
        <template v-else-if="displayState.key === 'permission'">
          <Clock :size="14" class="text-warn" />
        </template>
        <template v-else-if="displayState.key === 'denied'">
          <Ban v-if="!isPlanConstrained" :size="14" class="text-error" />
          <AlertCircle v-else :size="14" class="text-warn" />
        </template>
        <template v-else-if="displayState.key === 'failed'">
          <AlertCircle :size="14" class="text-error" />
        </template>
        <template v-else-if="displayState.key === 'success'">
          <Check :size="14" class="text-success" />
        </template>
      </span>
      <ChevronRight :size="14" class="expand-arrow" :class="{ rotated: isExpanded }" />
    </div>

    <div v-if="isExpanded" class="tool-call-body">
      <!-- 阶段 C6: denied 原因（plan 只读 / preset 拒绝 / 用户拒绝 / 超时） -->
      <div v-if="displayState.key === 'denied'" class="tool-section">
        <div class="section-label">{{ t('agent.rejectReason') }}</div>
        <div class="denied-reason" :class="{ constrained: isPlanConstrained }">
          {{ deniedReasonText(displayState.reason) }}
        </div>
      </div>
      <!-- P0-2: 截断失败专属提示 -->
      <div v-if="displayState.key === 'failed' && displayState.reason === 'truncated'" class="tool-section">
        <div class="section-label">{{ t('agent.toolPart.failed.label') }}</div>
        <div class="denied-reason">{{ t('agent.toolPart.failed.truncated') }}</div>
      </div>
      <div v-if="toolCall" class="tool-section">
        <div class="section-label">{{ t('agent.parameters') }}</div>
        <pre class="tool-json"><code>{{ JSON.stringify(toolCall.arguments, null, 2) }}</code></pre>
      </div>
      <div v-if="toolResult" class="tool-section">
        <div class="section-label">{{ toolResult.success ? t('agent.result') : t('agent.toolPart.failed.label') }}</div>
        <pre class="tool-content" :class="{ 'error-text': !toolResult.success }"><code>{{ toolResult.content || toolResult.error }}</code></pre>
      </div>
      <!-- 6.3.2: 三态确认 — 仅本次/始终允许/拒绝(带原因) -->
      <div v-if="requiresApproval && !approved" class="tool-actions">
        <template v-if="!rejecting">
          <button class="btn-approve" @click.stop="approve('once')">
            <Check :size="14" /> {{ t('agent.approve') }}
          </button>
          <button class="btn-approve-always" @click.stop="approve('always')">
            <Check :size="14" /> {{ t('agent.approveAlways') }}
          </button>
          <button class="btn-reject" @click.stop="startReject">
            <X :size="14" /> {{ t('agent.reject') }}
          </button>
        </template>
        <div v-else class="reject-form">
          <textarea
            v-model="rejectFeedback"
            class="reject-input"
            :placeholder="t('agent.rejectReasonPlaceholder')"
            rows="2"
          />
          <div class="reject-actions">
            <button class="btn-reject" @click.stop="confirmReject">
              {{ t('agent.reject') }}
            </button>
            <button class="btn-cancel" @click.stop="cancelReject">
              {{ t('common.cancel') }}
            </button>
          </div>
        </div>
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

/* 阶段 C6: denied + plan_mode_readonly → 信息性"被约束"（黄色）而非错误 */
.tool-call-card.constrained {
  border-color: rgba(255, 149, 0, 0.45);
}

.tool-call-card.constrained .tool-call-header {
  background: rgba(255, 149, 0, 0.05);
}

[data-theme='light'] .tool-call-card.constrained .tool-call-header {
  background: rgba(255, 149, 0, 0.05);
}

.constrained-summary {
  color: var(--warning);
}

.text-warn {
  color: var(--warning);
}

.denied-reason {
  font-size: 12px;
  color: var(--danger);
}

.denied-reason.constrained {
  color: var(--warning);
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
.btn-approve-always,
.btn-reject,
.btn-cancel {
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

/* 6.3.2: 始终允许 — 用 accent 色与"仅本次"区分 */
.btn-approve-always {
  background: var(--accent);
  color: #fff;
}

.btn-approve-always:hover {
  filter: brightness(0.88);
}

.btn-reject {
  background: var(--danger);
  color: #fff;
}

.btn-reject:hover {
  filter: brightness(0.88);
}

/* 6.3.2: 拒绝原因输入区 */
.reject-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 4px;
}

.reject-input {
  width: 100%;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 12.5px;
  font-family: inherit;
  resize: vertical;
}

.reject-input:focus {
  outline: none;
  border-color: var(--accent);
}

.reject-actions {
  display: flex;
  gap: 8px;
}

.btn-cancel {
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}

.btn-cancel:hover {
  filter: brightness(0.96);
}
</style>
