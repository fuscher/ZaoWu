<script setup lang="ts">
import { computed, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import { User, Bot, Copy, Check, AlertTriangle } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useCommunityStore } from '@/stores/community'
import { useChatStore } from '@/stores/chat'
import { runRecoveryActions } from '@/utils/recoveryActions'
import type { Message, ToolCall, ToolResult, MessageQuality, ErrorPayload, PhaseNode, PhaseName } from '@/types'
import ToolCallCard from './ToolCallCard.vue'
import PhaseStrip from './PhaseStrip.vue'
import ErrorCard from './ErrorCard.vue'

const props = defineProps<{
  message: Message
  isStreaming?: boolean
  /** Optional collaboration sender name */
  senderName?: string
}>()

const communityStore = useCommunityStore()
const chatStore = useChatStore()
const { t } = useI18n()

/** 复制渲染后的纯文本（与拖选语义一致），pywebview 环境下作为整条复制的快捷入口 */
const copied = ref(false)
async function copyMessage() {
  // 取 markdown 渲染后的纯文本（去 #、** 等标记），与拖选复制的内容保持一致
  const html = renderedContent.value
  const div = document.createElement('div')
  div.innerHTML = html
  const text = div.innerText || props.message.content || ''
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // 非安全上下文（非 localhost）/WebView2 剪贴板 API 异常时的兜底
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const renderedContent = computed(() => {
  if (!props.message.content) return ''
  return md.render(props.message.content)
})

/**
 * Stage 9: 从已持久化的消息中配对还原工具调用+结果卡片。
 *
 * 修复点：
 * - F06: 将分开存储的 tool_call（assistant 消息）和 tool 结果（tool 消息）按
 *   tool_call_id 合并为一张卡片，而非各自独立渲染。
 * - F09: tool 角色消息的 content 不再通过 Markdown 渲染，避免与卡片双重显示。
 */
const pairedToolCalls = computed(() => {
  type Pair = { toolCall: ToolCall; toolResult?: ToolResult }
  const pairs: Pair[] = []

  if (props.message.role !== 'assistant' || !props.message.tool_calls) return pairs

  // 查找后续的 tool 结果消息（它们紧跟在 assistant 消息后面）
  const allMessages = chatStore.currentMessages
  const msgIndex = allMessages.findIndex((m) => m.id === props.message.id)
  if (msgIndex === -1) return pairs

  for (const tc of props.message.tool_calls) {
    const fn = (tc as any).function
    let args: Record<string, unknown> = {}
    try {
      args = fn?.arguments ? JSON.parse(fn.arguments) : (tc as any).arguments || {}
    } catch {
      args = {}
    }

    const toolCall: ToolCall = {
      requestId: tc.id,
      name: fn?.name || (tc as any).name || 'unknown',
      arguments: args,
    }

    // 在后续消息中查找匹配的 tool 结果（按 tool_call_id 配对）
    let toolResult: ToolResult | undefined
    for (let i = msgIndex + 1; i < allMessages.length; i++) {
      const m = allMessages[i]
      if (!m) break
      if (m.role !== 'tool') break
      if (m.tool_call_id === tc.id) {
        let success = true
        try {
          const parsed = JSON.parse(m.content)
          success = parsed.success !== false
        } catch {
          success = true
        }
        toolResult = {
          requestId: m.tool_call_id || '',
          tool: m.name || 'unknown',
          success,
          content: m.content,
        }
        break
      }
    }
    pairs.push({ toolCall, toolResult })
  }

  return pairs
})

const isUser = computed(() => props.message.role === 'user')
const timeStr = computed(() => {
  const d = new Date(props.message.timestamp)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
})

/** Display name for messages from other collaboration users */
/** 历史消息 PhaseStrip 回退（阶段 A6 落库的 metadata.phase_history） */
const legacyPhaseHistory = computed<PhaseNode[]>(() => {
  const history = props.message.metadata?.phase_history
  if (!history || history.length === 0) return []
  return history.map((phase) => ({
    phase: phase as PhaseName,
    ts: props.message.timestamp,
  }))
})

const phasesForStrip = computed<PhaseNode[]>(() => {
  const live = chatStore.phaseHistoryFor(props.message.id)
  if (live.length > 0) return live
  return legacyPhaseHistory.value
})

const displayName = computed(() => {
  if (isUser.value && props.senderName) return props.senderName
  if (isUser.value && communityStore.isInRoom && props.message.role === 'user') {
    return communityStore.currentUser?.name ?? 'You'
  }
  return isUser.value ? 'You' : 'ZaoWu'
})

// ── 阶段 C7: 完成质量分级 ─────────────────────────────────
// 优先读落库 metadata.quality；旧消息（无 quality）按正文内容回退推断，
// 覆盖 A 阶段之前落库的"空气泡"字面量（对齐 master C7 存量回退清单）。
function legacyQualityFromContent(content: string | null | undefined): MessageQuality | null {
  if (!content) return null
  if (content === '(completed)') return 'empty'
  if (content === '(已停止)') return 'stopped'
  if (content === '(检测到循环，已自动中断)') return 'stopped'
  if (content.startsWith('[请求失败:') || content.startsWith('(error:')) return 'error_fallback'
  if (content === '模型未生成有效响应，请重试。') return 'empty'
  if (content.startsWith('当前为计划模式（只读）')) return 'constrained'
  return null
}

/** 存量空气泡：字面量命中但该消息已不流式（历史消息），且无 metadata 时按 legacy 回退 */
const isLegacyFallback = computed(() => {
  const q = props.message.metadata?.quality
  if (q) return false
  return legacyQualityFromContent(props.message.content) !== null
})

const quality = computed<MessageQuality>(() => {
  const q = props.message.metadata?.quality
  if (q) return q
  return legacyQualityFromContent(props.message.content) ?? 'success'
})

/** 流式中/终态错误 payload（实时流来自 store.lastError；历史来自 metadata，含 recovery） */
const errorPayload = computed<ErrorPayload | null>(() => {
  const m = props.message.metadata
  if (m?.error_code || m?.error_message) {
    return {
      code: m.error_code || 'internal',
      message: m.error_message || '',
      traceId: m.error_trace_id,
      recovery: m.error_recovery,
    }
  }
  if (props.isStreaming && chatStore.streamingMessageId === props.message.id) {
    return chatStore.lastError
  }
  return null
})

/** 恢复 CTA（idle/empty → retry；constrained → 切执行模式 + 查看方案） */
const recoveryActions = computed(() => {
  switch (quality.value) {
    case 'idle':
    case 'empty':
    case 'incomplete':
      return [{ label: t('agent.recovery.retry'), action: 'retry' }]
    case 'constrained':
      return [
        { label: t('agent.recovery.switchToBuild'), action: 'switch_preset:build' },
        { label: t('agent.recovery.viewPlan'), action: 'scroll_to_plan' },
      ]
    default:
      return null
  }
})

const qualityMeta = computed(() => {
  switch (quality.value) {
    case 'idle': return { cls: 'idle', text: t('agent.quality.idle') }
    case 'constrained': return { cls: 'constrained', text: t('agent.quality.constrained') }
    case 'empty': return { cls: 'empty', text: t('agent.quality.empty') }
    case 'stopped': return { cls: 'stopped', text: t('agent.quality.stopped') }
    case 'incomplete': return { cls: 'incomplete', text: t('agent.quality.incomplete') }
    default: return null
  }
})

/** CTA 动作 → recoveryActions 注册表（Context 由 chatStore 提供） */
function handleRecoveryAction(action: string) {
  const conv = chatStore.currentConversation
  const lastUserMessage = [...(conv?.messages || [])]
    .reverse()
    .find((m) => m.role === 'user')?.content ?? ''
  runRecoveryActions([{ label: '', action }], {
    lastUserMessage,
    switchToBuild: async () => {
      await chatStore.switchToBuildAndResend()
    },
    openProviders: () => {
      window.dispatchEvent(new CustomEvent('zaowu:open-settings', { detail: { panel: 'providers' } }))
    },
    openModelSwitcher: () => {
      window.dispatchEvent(new CustomEvent('zaowu:open-model-switcher'))
    },
    clearMessages: async () => {
      // 无前置 user 消息时不清空（避免纯数据丢失且无重发）
      if (!lastUserMessage) return
      await chatStore.clearMessages()
      chatStore.sendAgentMessage(lastUserMessage)
    },
    scrollToPlan: () => {
      // 滚动到方案气泡：回退为滚动到当前消息
      props.message.id && document.getElementById(`msg-${props.message.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    },
    retry: () => {
      if (lastUserMessage) chatStore.sendAgentMessage(lastUserMessage)
    },
  })
}
</script>

<template>
  <div
    class="message-bubble"
    :id="`msg-${message.id}`"
    :class="[
      { user: isUser, assistant: !isUser },
      qualityMeta || isLegacyFallback ? `quality-${quality}` : '',
    ]"
  >
    <div class="avatar">
      <User v-if="isUser" :size="16" />
      <Bot v-else :size="16" />
    </div>
    <div class="bubble-body">
      <div class="bubble-header">
        <span class="role-name">{{ displayName }}</span>
        <span class="time">{{ timeStr }}</span>
        <button
          v-if="message.content && !isStreaming"
          class="copy-btn"
          :title="t('chat.copyMessage')"
          @click.stop="copyMessage"
        >
          <Check v-if="copied" :size="12" />
          <Copy v-else :size="12" />
        </button>
      </div>
      <!-- 阶段 C3: PhaseStrip 展示本轮 agent 阶段流转（实时事件 + 历史 metadata 回退） -->
      <PhaseStrip
        v-if="!isUser && phasesForStrip.length > 0"
        :phases="phasesForStrip"
        :is-streaming="isStreaming"
      />
      <div v-if="isUser" class="content-text">{{ message.content }}</div>
      <!-- F09: tool 角色消息的 content 不再通过 Markdown 渲染，结果仅通过配对卡片显示 -->
      <div v-else-if="message.role === 'tool'" class="content-text tool-result-text" />
      <!-- 阶段 C7: error_fallback 挂 ErrorCard（替代正文）；无结构化 payload 的历史错误保留原文 -->
      <div
        v-else-if="quality === 'error_fallback' && !errorPayload"
        class="content-text error-fallback-text"
      >
        {{ message.content }}
      </div>
      <div v-else-if="quality === 'stopped'" class="content-text stopped-text">
        {{ t('agent.quality.stopped') }}
      </div>
      <!-- 仅当有正文才渲染 markdown 区：工具调用轮 assistant 消息 content 为 null
           （OpenAI 标准格式），渲染空 div 会形成"空气泡"，直接跳过正文区 -->
      <div v-else-if="renderedContent" class="content-md" v-html="renderedContent" />
      <!-- Stage 9: 实时工具调用卡片（仅当前正在流式生成的消息） -->
      <div
        v-if="!isUser && isStreaming && chatStore.streamingMessageId === message.id"
        class="tool-calls"
      >
        <ToolCallCard
          v-for="[requestId, result] in chatStore.toolResultsFor(message.id)"
          :key="requestId"
          :tool-call="chatStore.toolCallsFor(message.id).get(requestId)"
          :tool-result="result"
          :part="chatStore.toolPartsFor(message.id).get(requestId)"
          :requires-approval="chatStore.pendingFor(message.id).has(requestId)"
          @approve="(id, scope) => chatStore.confirmTool(id, true, scope)"
          @reject="(id, feedback) => chatStore.confirmTool(id, false, 'once', feedback)"
        />
        <ToolCallCard
          v-for="[requestId, toolCall] in chatStore.pendingFor(message.id)"
          :key="`pending-${requestId}`"
          :tool-call="toolCall"
          :requires-approval="true"
          @approve="(id, scope) => chatStore.confirmTool(id, true, scope)"
          @reject="(id, feedback) => chatStore.confirmTool(id, false, 'once', feedback)"
        />
      </div>
      <!-- Stage 9: 历史工具调用配对卡片（合并 call + result） -->
      <div v-if="!isUser && pairedToolCalls.length > 0" class="tool-calls">
        <ToolCallCard
          v-for="(pair, index) in pairedToolCalls"
          :key="index"
          :tool-call="pair.toolCall"
          :tool-result="pair.toolResult"
        />
      </div>
      <div v-if="isStreaming && !isUser" class="streaming-indicator">
        <span class="dot" /><span class="dot" /><span class="dot" />
      </div>
      <!-- 阶段 C7: 完成态分级 — 错误挂 ErrorCard；idle/empty/constrained 挂 CTA 条 -->
      <ErrorCard
        v-if="errorPayload && !isUser"
        :error="errorPayload"
        @action="handleRecoveryAction"
      />
      <div
        v-else-if="qualityMeta && !isStreaming && !isUser"
        class="quality-bar"
        :class="qualityMeta.cls"
      >
        <AlertTriangle :size="12" />
        <span>{{ qualityMeta.text }}</span>
        <template v-if="recoveryActions">
          <button
            v-for="(r, i) in recoveryActions"
            :key="i"
            class="quality-cta"
            @click="handleRecoveryAction(r.action)"
          >
            {{ r.label }}
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-bubble {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.message-bubble.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.user .avatar {
  background: var(--accent-hover);
  color: #fff;
}

.assistant .avatar {
  background: var(--bg-glass);
  color: var(--text-secondary);
  border: 1px solid var(--border-glass);
}

.bubble-body {
  min-width: 0;
  max-width: 80%;
}

.user .bubble-body {
  text-align: right;
}

.bubble-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: auto;
  padding: 2px 5px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  font-size: 11px;
  cursor: pointer;
  opacity: 0.45;
  transition: opacity var(--transition), background var(--transition), color var(--transition);
  user-select: none;
}

.copy-btn:hover {
  opacity: 1;
  color: var(--accent);
  background: var(--bg-glass);
}

.user .copy-btn {
  margin-left: 0;
  margin-right: auto;
}

.user .bubble-header {
  flex-direction: row-reverse;
}

.role-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.time {
  font-size: 11px;
  color: var(--text-tertiary);
}

.content-text {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  user-select: text;
  -webkit-user-select: text;
}

.content-md {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-primary);
  word-break: break-word;
  user-select: text;
  -webkit-user-select: text;
}

.content-md :deep(p) {
  margin: 0 0 8px;
}

.content-md :deep(p:last-child) {
  margin-bottom: 0;
}

.content-md :deep(code) {
  background: var(--bg-glass);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12.5px;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
}

.content-md :deep(pre) {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  margin: 8px 0;
}

.content-md :deep(pre code) {
  background: none;
  padding: 0;
  font-size: 12.5px;
}

.content-md :deep(ul),
.content-md :deep(ol) {
  padding-left: 20px;
  margin: 4px 0;
}

.content-md :deep(blockquote) {
  border-left: 3px solid var(--accent);
  padding-left: 12px;
  color: var(--text-secondary);
  margin: 8px 0;
}

.content-md :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
}

.content-md :deep(th),
.content-md :deep(td) {
  border: 1px solid var(--border-subtle);
  padding: 6px 10px;
  text-align: left;
  font-size: 12.5px;
}

.content-md :deep(th) {
  background: var(--bg-glass);
}

.streaming-indicator {
  display: flex;
  gap: 4px;
  padding-top: 4px;
}

.tool-calls {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-tertiary);
  animation: pulse 1.4s infinite;
}

/* ── 阶段 C7: 完成态分级样式 ─────────────────────────────── */
/* idle/empty: 黄色边 + 警告 CTA 条；constrained: 蓝色边；error_fallback: 红色边 */

.quality-idle .bubble-body,
.quality-empty .bubble-body,
.quality-incomplete .bubble-body {
  border: 1px solid rgba(255, 149, 0, 0.4);
  border-radius: 12px;
  padding: 8px 12px;
}

.quality-constrained .bubble-body {
  border: 1px solid var(--accent-muted);
  border-radius: 12px;
  padding: 8px 12px;
}

.quality-error_fallback .bubble-body {
  border: 1px solid var(--danger);
  border-radius: 12px;
  padding: 8px 12px;
}

.quality-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12px;
}

.quality-bar.idle,
.quality-bar.empty,
.quality-bar.incomplete {
  color: var(--warning);
  background: rgba(255, 149, 0, 0.08);
}

.quality-bar.constrained {
  color: var(--accent);
  background: var(--accent-muted);
}

.quality-cta {
  margin-left: 2px;
  padding: 3px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  color: var(--text-secondary);
  font-size: 11.5px;
  cursor: pointer;
  transition: all var(--transition);
  white-space: nowrap;
}

.quality-cta:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.stopped-text {
  color: var(--text-tertiary);
  font-style: italic;
}

.error-fallback-text {
  color: var(--danger);
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}
</style>
