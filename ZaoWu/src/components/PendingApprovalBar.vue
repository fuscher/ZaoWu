<script setup lang="ts">
/**
 * 阶段 C10: 全局审批浮层 — ChatInput 上方固定条。
 *
 * 目标：让「批准/始终允许/拒绝」不依赖消息气泡位置与展开状态（原交互需
 * 滚动到气泡 + 点开 ToolCallCard 才能操作）。参考 Claude Code 终端内联
 * prompt（y/n/a）与 opencode 模态 dialog 的共性：审批永远在用户视线内。
 *
 * 能力：
 * - 聚合 chatStore.pendingApprovals（跨 messageId），队列展示第一个 + 序号
 * - 三态按钮：批准(once) / 始终允许(always) / 拒绝(once)
 * - 超时倒计时（与后端 CONFIRMATION_TIMEOUT=60s 对齐），最后 10s 变红
 * - 快捷键：Enter=批准 / 2=始终允许 / Esc=拒绝；输入框聚焦时豁免（防打字冲突）
 *
 * 设计约束（奥卡姆剃刀）：固定条而非遮罩 Modal（不打断阅读）；复用现有
 * confirmTool / ToolCall 类型 / i18n，不引入新状态机。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'

// 与后端 agent_service.CONFIRMATION_TIMEOUT 对齐（秒）
const CONFIRM_TIMEOUT = 60

const chatStore = useChatStore()
const { t } = useI18n()

const pendingApprovals = computed(() => chatStore.pendingApprovals)
// 当前展示项 = 队列第一个（多 pending 排队；翻页交互留待 P1，当前固定首个）
const current = computed(() => pendingApprovals.value[0] ?? null)
const total = computed(() => pendingApprovals.value.length)
const currentKey = computed(() =>
  current.value ? `${current.value.messageId}:${current.value.requestId}` : ''
)

/** 参数摘要：JSON 截断 120 字符，避免浮层过长 */
const paramsSummary = computed(() => {
  if (!current.value) return ''
  try {
    const s = JSON.stringify(current.value.toolCall.arguments)
    return s.length > 120 ? `${s.slice(0, 120)}…` : s
  } catch {
    return ''
  }
})

// ── 倒计时（FIX-3：对齐后端超时——自请求发起时刻起算，非每队列项重置）──
// 后端 CONFIRMATION_TIMEOUT 自「该请求被 ask」起算；队列后续项显示真实剩余，
// 而非切换到它时才重新计满 60s。
const now = ref(Date.now())
let timer: number | null = null

function startCountdown() {
  stopCountdown()
  now.value = Date.now()
  timer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
}

function stopCountdown() {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

const currentRequestedAt = computed(() =>
  current.value ? chatStore.pendingRequestedAt.get(current.value.requestId) ?? Date.now() : 0
)

// 当前审批项剩余秒数（真实剩余；无 pending 时回满值供展示）
const remaining = computed(() => {
  if (!current.value) return CONFIRM_TIMEOUT
  const elapsed = Math.max(0, Math.floor((now.value - currentRequestedAt.value) / 1000))
  return Math.max(0, CONFIRM_TIMEOUT - elapsed)
})

// 当前审批项变化（出现/切换/清空）→ 重置倒计时
watch(currentKey, (k) => {
  if (k) startCountdown()
  else stopCountdown()
})

// FIX-3：剩余归零且后端超时事件未到达 → 防御性移除该 pending（后端已超时拒绝，
// 防止残留卡住浮层；随后到达的 tool_call_end 为无害 no-op）
watch(remaining, (r) => {
  if (current.value && r <= 0) {
    chatStore.dismissPending(current.value.requestId)
  }
})

// ── 动作 ────────────────────────────────────────────────
// 提交中状态：点击后立即禁用按钮并短暂显示「已提交」，避免用户误以为
// 点击无响应（确认请求为异步，成功时由 tool_call_end 清除 pending 驱动
// 浮层消失；若 pending 仍在则 600ms 后恢复可点）。
const submitting = ref(false)
let submitTimer: number | null = null

function beginSubmit() {
  submitting.value = true
  if (submitTimer !== null) clearTimeout(submitTimer)
  submitTimer = window.setTimeout(() => {
    submitting.value = false
    submitTimer = null
  }, 600)
}

function approve(scope: 'once' | 'always') {
  if (!current.value || submitting.value) return
  beginSubmit()
  chatStore.confirmTool(current.value.requestId, true, scope)
}

function reject() {
  if (!current.value || submitting.value) return
  beginSubmit()
  chatStore.confirmTool(current.value.requestId, false, 'once')
}

// ── 快捷键（输入框聚焦豁免，防打字冲突） ─────────────────
function isTypingTarget(el: Element | null): boolean {
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || (el as HTMLElement).isContentEditable
}

function onKeydown(e: KeyboardEvent) {
  if (pendingApprovals.value.length === 0) return
  if (isTypingTarget(document.activeElement)) return
  // FIX-2：弹窗/遮罩打开时一律跳过——按 Esc 关闭弹窗不应静默拒绝待确认工具
  if (document.querySelector('[role="dialog"], [class*="overlay"]')) return
  // FIX-2：事件目标是交互控件（按钮/链接/下拉）时跳过——按 Enter 激活按钮不应同时批准
  if ((e.target as HTMLElement)?.closest?.('button, a, select, [role="button"], [contenteditable="true"]')) return
  const plain = !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey
  if (e.key === 'Enter' && plain) {
    e.preventDefault()
    approve('once')
  } else if (e.key === '2' && plain) {
    e.preventDefault()
    approve('always')
  } else if (e.key === 'Escape') {
    e.preventDefault()
    reject()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  if (pendingApprovals.value.length > 0) startCountdown()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  stopCountdown()
})
</script>

<template>
  <Transition name="approval-slide">
    <div v-if="pendingApprovals.length > 0" class="approval-bar" role="alert">
      <div class="approval-info">
        <div class="approval-title-row">
          <span class="approval-dot" />
          <span class="approval-title">{{ t('agent.approvalBar.title') }}</span>
          <span v-if="total > 1" class="approval-queue">
            {{ t('agent.approvalBar.queue', { current: 1, total }) }}
          </span>
        </div>
        <div v-if="current" class="approval-tool">
          <span class="tool-name">{{ current.toolCall.name }}</span>
          <span v-if="paramsSummary" class="tool-params">{{ paramsSummary }}</span>
        </div>
        <div
          class="approval-countdown"
          :class="{ urgent: remaining <= 10 && remaining > 0, expired: remaining === 0 }"
        >
          {{
            remaining > 0
              ? t('agent.approvalBar.countdown', { n: remaining })
              : t('agent.approvalBar.timeout')
          }}
        </div>
      </div>
      <div class="approval-actions">
        <button class="btn-approve" :disabled="submitting" @click="approve('once')">
          {{ submitting ? t('agent.approvalBar.submitted') : t('agent.approvalBar.approveOnceShort') }}
        </button>
        <button class="btn-approve-always" :disabled="submitting" @click="approve('always')">
          {{ submitting ? t('agent.approvalBar.submitted') : t('agent.approvalBar.approveAlwaysShort') }}
        </button>
        <button class="btn-reject" :disabled="submitting" @click="reject">
          {{ submitting ? t('agent.approvalBar.submitted') : t('agent.approvalBar.rejectShort') }}
        </button>
      </div>
      <span class="approval-hint">{{ t('agent.approvalBar.hint') }}</span>
    </div>
  </Transition>
</template>

<style scoped>
.approval-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 0 16px 8px;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid var(--accent-muted, var(--border-glass));
  background: var(--bg-glass);
  box-shadow: 0 2px 10px var(--shadow);
  flex-shrink: 0;
}

.approval-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.approval-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.approval-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--warning, #ff9500);
  flex-shrink: 0;
  animation: approval-pulse 1.2s ease-in-out infinite;
}

@keyframes approval-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.approval-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.approval-queue {
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--bg-secondary);
  border-radius: 4px;
  padding: 1px 6px;
}

.approval-tool {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.tool-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  flex-shrink: 0;
}

.tool-params {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.approval-countdown {
  font-size: 11px;
  color: var(--text-tertiary);
}

.approval-countdown.urgent {
  color: var(--danger);
  font-weight: 600;
}

.approval-countdown.expired {
  color: var(--danger);
}

.approval-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* 配色统一：三个审批按钮同一中性主题色（参考工作流 .launcher-btn），
   随明暗主题自适应（--bg-tertiary/--border-subtle/--text-primary/--bg-hover）；
   语义差异仅靠文字表达（批准/始终允许/拒绝），不做红绿蓝强语义色区分。 */
.btn-approve,
.btn-approve-always,
.btn-reject {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 8px 14px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-size: 13px;
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.15s, opacity 0.15s;
}

.btn-approve:hover:not(:disabled),
.btn-approve-always:hover:not(:disabled),
.btn-reject:hover:not(:disabled) {
  background: var(--bg-hover);
}

.btn-approve:disabled,
.btn-approve-always:disabled,
.btn-reject:disabled {
  opacity: 0.55;
  cursor: default;
}

.approval-hint {
  font-size: 11px;
  color: var(--text-tertiary);
  flex-shrink: 0;
  white-space: nowrap;
}

/* 入场/出场：轻微下滑 + 淡入（浮层在 ChatInput 上方出现） */
.approval-slide-enter-active,
.approval-slide-leave-active {
  transition: all 0.18s ease;
}

.approval-slide-enter-from,
.approval-slide-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
