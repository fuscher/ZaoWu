<script setup lang="ts">
/**
 * S14-P0-1: 项目指示器 — 对话↔项目绑定（沙箱限缩）入口。
 *
 * 仿 ModelSwitcher 下拉范式（dropdownRef + handleClickOutside + Transition）。
 * - 未绑定 → 「全部文件夹 (N)」；绑定 → 「已指定：A」
 * - 候选 = activeProjects 中已注册、未归档、非虚拟项（G1）
 * - G2/G8 (NEW-1)：绑定失效 → 回退「全部文件夹 (N)」并 toast 一次
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { FolderOpen, Folder, ChevronDown } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useProjectsStore } from '@/stores/projects'
import { useI18n } from '@/i18n'
import ErrorToast from './ErrorToast.vue'

const chatStore = useChatStore()
const projectsStore = useProjectsStore()
const { t } = useI18n()
const isOpen = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)

/** 可选候选：已注册、未归档、非虚拟（G1 过滤虚拟项目） */
const candidates = computed(() =>
  projectsStore.activeProjects.filter((p) => !p.virtual && !p.archived)
)

const bound = computed(() => chatStore.sandboxProject)

const label = computed(() => {
  if (bound.value) return `${t('agent.sandbox.bound')}：${bound.value.name}`
  return `${t('agent.sandbox.all')} (${candidates.value.length})`
})

const activeItem = computed(() => bound.value?.id ?? '')

/** G2: 失效检测 → toast 一次（指示器读取 sandboxProject 时置位） */
const toastMessage = ref('')
watch(
  () => chatStore.sandboxInvalidated,
  (v) => {
    if (v) {
      toastMessage.value = t('agent.sandbox.invalid')
      chatStore.ackSandboxInvalidation()
    }
  },
  { immediate: true }
)

/** 同名项目消歧：name 重复时附短路径 */
const nameDuplicates = computed(() => {
  const count = new Map<string, number>()
  for (const p of candidates.value) count.set(p.name, (count.get(p.name) || 0) + 1)
  return count
})

function toggle() {
  isOpen.value = !isOpen.value
}

async function selectNone() {
  chatStore.sandboxProject = null
  isOpen.value = false
}

async function selectProject(project: { id: string; name: string; path: string }) {
  chatStore.sandboxProject = project as any
  isOpen.value = false
}

function handleClickOutside(e: Event) {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  if (projectsStore.projects.length === 0 && projectsStore.virtualProjects.length === 0) {
    projectsStore.fetchProjects()
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="project-indicator" ref="dropdownRef">
    <button
      class="indicator-trigger"
      :class="{ bound: !!bound }"
      :title="t('agent.sandbox.bindHint')"
      @click="toggle"
    >
      <FolderOpen v-if="bound" :size="13" />
      <Folder v-else :size="13" />
      <span class="indicator-label">{{ label }}</span>
      <ChevronDown :size="12" class="chevron" :class="{ open: isOpen }" />
    </button>

    <Transition name="dropdown">
      <div v-if="isOpen" class="dropdown">
        <div
          class="menu-item top"
          :class="{ active: !activeItem }"
          :title="t('agent.sandbox.unbind')"
          @click="selectNone"
        >
          <span>{{ t('agent.sandbox.all') }} ({{ candidates.length }})</span>
        </div>
        <div v-if="candidates.length === 0" class="dropdown-empty">
          {{ t('agent.sandbox.empty') }}
        </div>
        <div v-else class="menu-scroll">
          <div
            v-for="p in candidates"
            :key="p.id"
            class="menu-item"
            :class="{ active: activeItem === p.id }"
            @click="selectProject(p)"
          >
            <span class="item-name">{{ p.name }}</span>
            <span v-if="nameDuplicates.get(p.name)! > 1" class="item-path" :title="p.path">
              {{ p.path }}
            </span>
            <span class="item-id">{{ p.id.slice(0, 6) }}</span>
          </div>
        </div>
      </div>
    </Transition>

    <ErrorToast
      v-if="toastMessage"
      :message="toastMessage"
      type="warning"
      @close="toastMessage = ''"
    />
  </div>
</template>

<style scoped>
.project-indicator {
  position: relative;
  flex-shrink: 0;
}

.indicator-trigger {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 11.5px;
  transition: all var(--transition);
  white-space: nowrap;
  max-width: 200px;
}

.indicator-trigger:hover {
  background: var(--bg-glass-hover);
  border-color: var(--border-hover);
  color: var(--text-secondary);
}

.indicator-trigger.bound {
  border-color: var(--accent-muted);
  color: var(--accent);
}

.indicator-label {
  overflow: hidden;
  text-overflow: ellipsis;
}

.chevron {
  transition: transform var(--transition);
  flex-shrink: 0;
}

.chevron.open {
  transform: rotate(180deg);
}

.dropdown {
  position: absolute;
  bottom: calc(100% + 4px);
  right: 0;
  min-width: 240px;
  max-height: 280px;
  background: var(--bg-primary);
  border: 1px solid var(--border-glass);
  border-radius: 10px;
  padding: 6px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  z-index: 100;
  display: flex;
  flex-direction: column;
}

.menu-scroll {
  max-height: 240px;
  overflow-y: auto;
}

.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.15s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-primary);
  transition: background var(--transition);
  white-space: nowrap;
  min-width: 0;
}

.menu-item:hover {
  background: var(--bg-glass-hover);
}

.menu-item.active {
  background: var(--accent-muted);
  color: var(--accent);
}

.menu-item.top {
  border-bottom: 1px solid var(--border-subtle);
  border-radius: 6px 6px 0 0;
  margin-bottom: 4px;
}

.item-name {
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
  min-width: 0;
}

.item-path {
  font-size: 10px;
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
  min-width: 0;
}

.item-id {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
}

.dropdown-empty {
  padding: 12px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}
</style>
