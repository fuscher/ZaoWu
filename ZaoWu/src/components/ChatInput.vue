<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { Send, Square, Bot, Sparkles, Hammer, ClipboardList } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useProjectsStore } from '@/stores/projects'
import { useI18n } from '@/i18n'
import { apiPathForProject } from '@/utils/api'
import { toRelPath } from '@/utils/refs'
import type { Project, TreeNode } from '@/types'
import ModelSwitcher from './ModelSwitcher.vue'
import ParameterPanel from './ParameterPanel.vue'
import ErrorToast from './ErrorToast.vue'
import ProjectIndicator from './ProjectIndicator.vue'
import MentionPopup from './MentionPopup.vue'

const chatStore = useChatStore()
const projectsStore = useProjectsStore()
const { t } = useI18n()
const isComposing = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

// S14: 草稿提升到 store（FileTree「引用到对话」与 @ 浮层共用插入逻辑）
const input = computed<string>({
  get: () => chatStore.draft,
  set: (v) => (chatStore.draft = v),
})

// 阶段 C8: 模式切换 toast（plan↔build 切换时提示约束变化）
const toastMessage = ref('')
const toastType = ref<'error' | 'warning' | 'info'>('info')
function showToast(message: string, type: 'error' | 'warning' | 'info' = 'info') {
  toastMessage.value = ''
  setTimeout(() => {
    toastMessage.value = message
    toastType.value = type
  })
}

async function setPreset(next: 'build' | 'plan') {
  if (chatStore.preset === next) return
  const ok = await chatStore.setPreset(next)
  // 仅在持久化成功时提示（失败已回退，避免误导用户以为切换成功）
  if (!ok) {
    showToast(t('agent.presetSwitchFailed'), 'warning')
    return
  }
  showToast(
    next === 'plan' ? t('agent.modeBadge.planHint') : t('agent.modeBadge.buildHint'),
    'info'
  )
}

// 自适应高度：从单行起随内容增长，最高 160px，超出则内部滚动
function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

function handleSend() {
  if (!input.value.trim() || isComposing.value) return
  closeMention()
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
  checkMention()
}

function handleStop() {
  chatStore.stopStreaming()
}

async function toggleAgentMode() {
  // S13-P0-3: Anthropic 供应商不支持 Agent 模式（Agent 链路仅 OpenAI 兼容协议），
  // 开关禁用时阻止切换，避免配置后发消息才报 PROTOCOL_UNSUPPORTED 的认知落差。
  if (agentUnsupported.value) return
  if (!chatStore.currentConversation) {
    await chatStore.createNewConversation()
  }
  chatStore.agentMode = !chatStore.agentMode
}

// S13-P0-3: 当前供应商为 Anthropic 时禁用 Agent 开关（currentProvider 由 chat.ts:584 导出）
const agentUnsupported = computed(
  () => chatStore.currentProvider?.protocol === 'anthropic'
)

// 技能改为「全部启用即生效」：仅展示当前已启用技能数量，设置模块启用的技能对所有对话生效
const enabledSkillsCount = computed(() =>
  chatStore.availableSkills.filter((s) => s.enabled).length
)

onMounted(() => {
  chatStore.loadSkills()
})

// ── S14-P1-1/P1-2: @ 引用浮层状态机 ───────────────────────────
// 第一层：项目列表（过滤虚拟项目 G1）；第二层：项目内文件树（get-tree 懒加载 G6）。
const MENTION_HINT_KEY = 'zaowu.mention.hintSeen'
const mentionOpen = ref(false)
const mentionLevel = ref<1 | 2>(1)
const mentionSelectedProject = ref<Project | null>(null)
const mentionFilter = ref('')       // 第二层过滤词（@<id>: 后的输入）
const mentionQuery = ref('')        // 已生效的过滤词（debounce 后）
const mentionTree = ref<TreeNode[]>([])
const mentionExpanded = ref<Set<string>>(new Set())
const mentionIndex = ref(0)
const mentionHintSeen = ref(false)
const mentionLoading = ref(false)
let mentionFilterTimer: number | undefined

const candidates = computed(() =>
  projectsStore.activeProjects.filter((p) => !p.virtual && !p.archived)
)

interface FlatNode {
  node: TreeNode
  depth: number
}

function flattenVisible(nodes: TreeNode[], expanded: Set<string>, depth = 0, out: FlatNode[] = []): FlatNode[] {
  for (const n of nodes) {
    out.push({ node: n, depth })
    if (n.type === 'directory' && n.children && expanded.has(n.path)) {
      flattenVisible(n.children, expanded, depth + 1, out)
    }
  }
  return out
}

function flattenAll(nodes: TreeNode[], depth = 0, out: FlatNode[] = []): FlatNode[] {
  for (const n of nodes) {
    out.push({ node: n, depth })
    if (n.type === 'directory' && n.children) {
      flattenAll(n.children, depth + 1, out)
    }
  }
  return out
}

/** 客户端树过滤（按名称包含，保留目录结构） */
function filterTree(nodes: TreeNode[], q: string): TreeNode[] {
  const out: TreeNode[] = []
  for (const n of nodes) {
    if (n.type === 'file') {
      if (n.name.toLowerCase().includes(q)) out.push(n)
    } else {
      const children = n.children ? filterTree(n.children, q) : []
      if (children.length || n.name.toLowerCase().includes(q)) {
        out.push({ ...n, children: children.length ? children : undefined })
      }
    }
  }
  return out
}

const mentionNodes = computed<FlatNode[]>(() => {
  if (!mentionSelectedProject.value) return []
  if (mentionQuery.value) return flattenAll(mentionTree.value).slice(0, 100)
  return flattenVisible(mentionTree.value, mentionExpanded.value)
})

const highlightIndex = computed(() => {
  const count = mentionLevel.value === 1 ? candidates.value.length : mentionNodes.value.length
  if (count === 0) return -1
  return Math.min(mentionIndex.value, count - 1)
})

/** 触发检测（G4: 仅 agent 模式；3.3: 行首/空白/标点后的 @ 才触发） */
function checkMention() {
  if (!chatStore.agentMode) {
    if (mentionOpen.value) closeMention()
    return
  }
  const el = textareaRef.value
  const caret = el ? el.selectionStart : input.value.length
  const before = input.value.slice(0, caret)

  // 第二层：@<id>: 后继续输入 = 项目内路径过滤（保持打开）
  if (mentionOpen.value && mentionLevel.value === 2 && mentionSelectedProject.value) {
    const prefix = `@${mentionSelectedProject.value.id}:`
    const idx = before.lastIndexOf(prefix)
    if (idx !== -1) {
      mentionFilter.value = before.slice(idx + prefix.length)
      return
    }
    closeMention()
    return
  }

  const triggered = /(?:^|[\s,.;:!?、。，；：！？])@$/.test(before)
  if (triggered) {
    if (!mentionOpen.value) {
      // S14-P0-1 联动: 绑定有效 → @ 跳过项目层直接第二层（3.2 单项目状态）
      const bound = chatStore.sandboxProject
      mentionOpen.value = true
      mentionLevel.value = bound ? 2 : 1
      mentionSelectedProject.value = bound
      mentionFilter.value = ''
      mentionQuery.value = ''
      mentionTree.value = []
      mentionExpanded.value = new Set()
      mentionIndex.value = 0
      if (bound) {
        replaceAtTokenWith(`@${bound.id}:`)
        loadTreeLevel2()
      }
      if (!localStorage.getItem(MENTION_HINT_KEY)) {
        mentionHintSeen.value = true
        localStorage.setItem(MENTION_HINT_KEY, '1')
      }
    }
  } else if (mentionOpen.value) {
    closeMention()
  }
}

function closeMention() {
  mentionOpen.value = false
  mentionLevel.value = 1
  mentionSelectedProject.value = null
  mentionFilter.value = ''
  mentionQuery.value = ''
  mentionTree.value = []
  mentionExpanded.value = new Set()
  mentionIndex.value = 0
  // 引导行仅首次触发展示（localStorage 已标记），关闭后重置避免残留
  mentionHintSeen.value = false
  if (mentionFilterTimer) {
    clearTimeout(mentionFilterTimer)
    mentionFilterTimer = undefined
  }
}

/** 把光标处未完成的 @ token 替换为指定文本（选中项目 → @<id>: 前缀） */
function replaceAtTokenWith(replacement: string) {
  const el = textareaRef.value
  const caret = el ? el.selectionStart : input.value.length
  const before = input.value.slice(0, caret)
  const m = /(?:^|[\s,.;:!?、。，；：！？])@$/.exec(before)
  const tokenStart = m ? m.index + (m[0].length - 1) : caret
  input.value = input.value.slice(0, tokenStart) + replacement + input.value.slice(caret)
  nextTick(() => {
    const ta = textareaRef.value
    if (ta) {
      ta.focus()
      const pos = tokenStart + replacement.length
      ta.setSelectionRange(pos, pos)
    }
  })
}

async function fetchTree(path: string, depth: number): Promise<TreeNode[]> {
  const p = mentionSelectedProject.value
  if (!p) return []
  try {
    const res = await fetch(apiPathForProject(p, '/explorer/get-tree'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, depth }),
    })
    const data = await res.json()
    return data.ok ? data.tree || [] : []
  } catch {
    return []
  }
}

/** 第二层：加载项目根树（depth=1，G6 显式逐层懒加载） */
async function loadTreeLevel2() {
  const p = mentionSelectedProject.value
  if (!p) return
  mentionLoading.value = true
  mentionTree.value = await fetchTree(p.path, 1)
  mentionLoading.value = false
}

/** 过滤模式：depth=3 + 客户端按名称过滤（限量 100） */
async function loadFilteredTree(q: string) {
  const p = mentionSelectedProject.value
  if (!p) return
  mentionLoading.value = true
  const raw = await fetchTree(p.path, 3)
  mentionTree.value = filterTree(raw, q.toLowerCase())
  mentionLoading.value = false
}

// 过滤 debounce 150ms（P1-2）
watch(mentionFilter, (q) => {
  mentionQuery.value = q
  if (mentionFilterTimer) clearTimeout(mentionFilterTimer)
  mentionFilterTimer = setTimeout(() => {
    if (mentionLevel.value !== 2) return
    if (q) loadFilteredTree(q)
    else loadTreeLevel2()
  }, 150)
})

/** 选中项目 → 进入第二层（@<id>: 前缀替换 @ token，不隐式绑定） */
function selectProject(p: Project) {
  mentionSelectedProject.value = p
  mentionLevel.value = 2
  mentionFilter.value = ''
  mentionQuery.value = ''
  mentionTree.value = []
  mentionExpanded.value = new Set()
  mentionIndex.value = 0
  replaceAtTokenWith(`@${p.id}:`)
  loadTreeLevel2()
}

/** 展开目录：未加载 → 懒加载子层；已加载 → 折叠/展开 */
async function expandDir(node: TreeNode) {
  if (node.children !== undefined) {
    if (mentionExpanded.value.has(node.path)) mentionExpanded.value.delete(node.path)
    else mentionExpanded.value.add(node.path)
    return
  }
  mentionLoading.value = true
  const children = await fetchTree(node.path, 1)
  node.children = children
  mentionExpanded.value.add(node.path)
  mentionLoading.value = false
}

/** 选中文件 → 插入内部标记 @{projectId}:relpath（统一 insertReference 实现） */
function selectFile(node: TreeNode) {
  const p = mentionSelectedProject.value
  if (!p) return
  const rel = toRelPath(node.path, p.path)
  chatStore.insertReference(p.id, rel)
  closeMention()
}

/** 回退第一层（Backspace/ESC/返回按钮） */
function goBack() {
  if (mentionLevel.value === 2 && mentionSelectedProject.value) {
    const el = textareaRef.value
    const caret = el ? el.selectionStart : input.value.length
    const before = input.value.slice(0, caret)
    const prefix = `@${mentionSelectedProject.value.id}:`
    const idx = before.lastIndexOf(prefix)
    if (idx !== -1) {
      input.value = input.value.slice(0, idx) + '@' + input.value.slice(idx + prefix.length)
      nextTick(() => {
        const ta = textareaRef.value
        if (ta) {
          ta.focus()
          ta.setSelectionRange(idx + 1, idx + 1)
        }
      })
    }
  }
  mentionLevel.value = 1
  mentionSelectedProject.value = null
  mentionFilter.value = ''
  mentionQuery.value = ''
  mentionTree.value = []
  mentionExpanded.value = new Set()
  mentionIndex.value = 0
}

// G3: 浮层打开期间 handleKeydown 吞掉 Enter（禁止误发消息）
function handleKeydown(e: KeyboardEvent) {
  if (mentionOpen.value) {
    const count = mentionLevel.value === 1 ? candidates.value.length : mentionNodes.value.length
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      mentionIndex.value = count > 0 ? (mentionIndex.value + 1) % count : 0
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      mentionIndex.value = count > 0 ? (mentionIndex.value - 1 + count) % count : 0
      return
    }
    if (e.key === 'Enter' && !e.shiftKey && !isComposing.value) {
      e.preventDefault()
      const hi = highlightIndex.value
      if (hi < 0) return
      if (mentionLevel.value === 1) {
        const p = candidates.value[hi]
        if (p) selectProject(p)
      } else {
        const item = mentionNodes.value[hi]
        if (item) {
          if (item.node.type === 'directory') expandDir(item.node)
          else selectFile(item.node)
        }
      }
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      closeMention()
      return
    }
    if (e.key === 'Backspace') {
      // 第二层且 @<id>: 前缀后无输入 → 回退第一层；否则默认退格
      if (mentionLevel.value === 2 && mentionSelectedProject.value) {
        const el = textareaRef.value
        const caret = el ? el.selectionStart : input.value.length
        const before = input.value.slice(0, caret)
        const prefix = `@${mentionSelectedProject.value.id}:`
        if (before.endsWith(prefix)) {
          e.preventDefault()
          goBack()
        }
      }
      return
    }
    return
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

// 外部插入（FileTree「引用到对话」）→ 聚焦输入框
watch(
  () => chatStore.focusRequestId,
  () => {
    nextTick(() => {
      textareaRef.value?.focus()
      autoResize()
    })
  }
)
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
    <!-- S14-P1-1: @ 引用浮层（固定定位，MVP 不做光标跟随） -->
    <MentionPopup
      v-if="mentionOpen"
      :level="mentionLevel"
      :projects="candidates"
      :nodes="mentionNodes"
      :loading="mentionLoading"
      :hint="mentionHintSeen"
      :query="mentionQuery"
      :highlight="highlightIndex"
      :selected-project="mentionSelectedProject"
      @select-project="selectProject"
      @select-file="selectFile"
      @expand-dir="expandDir"
      @back="goBack"
      @close="closeMention"
    />
    <div class="input-footer">
      <div class="footer-left">
        <ModelSwitcher />
        <ParameterPanel />
        <button
          class="agent-toggle"
          :class="{ active: chatStore.agentMode }"
          :disabled="agentUnsupported"
          :title="agentUnsupported
            ? t('agent.agentModeAnthropicUnsupported')
            : (chatStore.agentMode ? t('agent.agentModeDesc') : t('agent.agentMode'))"
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
            @click="setPreset('build')"
          >
            <Hammer :size="13" />
            {{ t('agent.presetModeBuild') }}
          </button>
          <button
            type="button"
            class="preset-btn"
            :class="{ active: chatStore.preset === 'plan' }"
            @click="setPreset('plan')"
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
      <div class="footer-right">
        <!-- S14-P0-1: 项目指示器（仅 agent 模式显示） -->
        <ProjectIndicator v-if="chatStore.agentMode" />
        <!-- 非 agent 模式显示快捷键提示；agent 模式下隐藏，避免流式期间该行变宽破坏单行布局 -->
        <span v-if="!chatStore.agentMode" class="hint">
          {{ t('chat.shortcutHint') }}
        </span>
      </div>
    </div>
    <!-- 阶段 C8: 模式切换 toast（固定定位已由 ErrorToast 自含） -->
    <ErrorToast v-if="toastMessage" :message="toastMessage" :type="toastType" @close="toastMessage = ''" />
  </div>
</template>

<style scoped>
.chat-input {
  padding: 12px 16px;
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
  position: relative;
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
  /* 强制单行：6 个控件 + 项目指示器全部在同一行；
     空间不足时由 model-name 等可收缩项（ellipsis）吸收，避免整体断裂换行 */
  flex-wrap: nowrap;
  gap: 4px 8px;
  margin-top: 6px;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 3px;
  min-width: 0;
  flex-wrap: nowrap;
}

.footer-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
}

.agent-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
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
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  color: var(--text-tertiary);
  font-size: 11px;
  white-space: nowrap;
}

/* 6.3.1: 预设模式切换器 — 分段按钮 */
.preset-switcher {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  padding: 1px;
  border-radius: 6px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.preset-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
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
  gap: 5px;
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
