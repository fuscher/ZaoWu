<script setup lang="ts">
/**
 * S14-P1-1 / P1-2: @ 引用浮层（展示层）。
 *
 * 第一层：项目列表（过滤虚拟项目，G1）；无项目 → 引导；首次触发顶部引导行。
 * 第二层：项目内文件树（get-tree 懒加载，G6——逐层请求，不在本组件请求，
 * 由 ChatInput 负责获取，本组件只负责渲染与事件上抛）。
 */
import { computed } from 'vue'
import { ChevronLeft, Folder, FolderOpen, File, Search, Sparkles } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { Project, TreeNode } from '@/types'

const props = defineProps<{
  level: 1 | 2
  projects: Project[]
  /** 第二层可见节点（已按展开状态扁平化，含 depth 缩进） */
  nodes: Array<{ node: TreeNode; depth: number }>
  loading: boolean
  /** 首次触发引导行 */
  hint: boolean
  /** 第二层过滤词 */
  query: string
  /** 键盘高亮索引 */
  highlight: number
  /** 当前选中项目（第二层展示路径上下文） */
  selectedProject: Project | null
}>()

const emit = defineEmits<{
  'select-project': [project: Project]
  'select-file': [node: TreeNode]
  'expand-dir': [node: TreeNode]
  back: []
  close: []
}>()

const { t } = useI18n()

const noProjects = computed(() => props.projects.length === 0)
</script>

<template>
  <div class="mention-popup">
    <!-- 首次引导行（localStorage 标记，仅首次触发展示） -->
    <div v-if="hint" class="hint-line">
      <Sparkles :size="12" />
      <span>{{ t('agent.mention.firstTime') }}</span>
    </div>

    <!-- 第一层：项目列表 -->
    <template v-if="level === 1">
      <div v-if="noProjects" class="no-projects" @click="emit('close')">
        {{ t('agent.mention.noProjects') }}
      </div>
      <div v-else class="menu-scroll">
        <div
          v-for="(p, i) in projects"
          :key="p.id"
          class="menu-item"
          :class="{ active: i === highlight }"
          @click="emit('select-project', p)"
          @mouseenter.prevent
        >
          <Folder :size="14" />
          <span class="item-name">{{ p.name }}</span>
          <span class="item-id">{{ p.id.slice(0, 6) }}</span>
        </div>
      </div>
    </template>

    <!-- 第二层：项目内文件/目录（懒加载展开） -->
    <template v-else>
      <div class="level2-header">
        <button class="back-btn" :title="t('agent.sandbox.unbind')" @click="emit('back')">
          <ChevronLeft :size="13" />
        </button>
        <span class="level2-title">
          <FolderOpen :size="13" />
          <span class="item-name">{{ selectedProject?.name || '' }}</span>
        </span>
      </div>
      <div v-if="query" class="filter-line">
        <Search :size="11" />
        <span>{{ query }}</span>
      </div>
      <div v-if="loading" class="loading-line">
        <svg width="12" height="12" viewBox="0 0 12 12" class="spin">
          <circle cx="6" cy="6" r="5" stroke="currentColor" stroke-width="1.5" fill="none" stroke-dasharray="20 12"/>
        </svg>
      </div>
      <div v-else-if="nodes.length === 0" class="no-projects">
        {{ t('fileTree.empty') }}
      </div>
      <div v-else class="menu-scroll">
        <div
          v-for="(item, i) in nodes"
          :key="item.node.path"
          class="menu-item"
          :class="{ active: i === highlight }"
          :style="{ paddingLeft: 10 + item.depth * 14 + 'px' }"
          @click="
            item.node.type === 'directory'
              ? emit('expand-dir', item.node)
              : emit('select-file', item.node)
          "
        >
          <Folder v-if="item.node.type === 'directory' && !item.node.children" :size="14" />
          <FolderOpen v-else-if="item.node.type === 'directory'" :size="14" />
          <File v-else :size="14" />
          <span class="item-name">{{ item.node.name }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.mention-popup {
  position: fixed;
  left: 16px;
  right: 16px;
  bottom: 132px;
  z-index: 120;
  background: var(--bg-primary);
  border: 1px solid var(--border-glass);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
  max-width: 420px;
  margin: 0 auto;
  overflow: hidden;
}

.hint-line {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  font-size: 11px;
  color: var(--accent);
  background: var(--accent-muted);
  border-bottom: 1px solid var(--border-subtle);
}

.menu-scroll {
  max-height: 240px;
  overflow-y: auto;
  padding: 4px;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12.5px;
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

.item-name {
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
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

.no-projects {
  padding: 16px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
  cursor: pointer;
}

.no-projects:hover {
  color: var(--accent);
}

.level2-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-subtle);
}

.back-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 4px;
  flex-shrink: 0;
}

.back-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--accent);
}

.level2-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 0;
  flex: 1;
}

.filter-line {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  border-bottom: 1px solid var(--border-subtle);
}

.loading-line {
  display: flex;
  justify-content: center;
  padding: 12px;
  color: var(--text-tertiary);
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
