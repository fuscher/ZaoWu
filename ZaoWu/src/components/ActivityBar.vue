<script setup lang="ts">
import { computed } from 'vue'
import {
  MessageSquare, FolderTree, Search, GitBranch, Puzzle, Users, Settings,
  Sun, Moon, Zap, Smile, Bell, Star, Heart, AlertCircle,
  type LucideIcon,
} from '@lucide/vue'
import { useI18n } from '@/i18n'
import { usePluginsStore, type PluginAction } from '@/stores/plugins'
import { pluginEventBus } from '@/plugin-system/events'
import type { Theme, ViewType } from '@/types'

defineProps<{ activeView: ViewType; theme: Theme }>()
const emit = defineEmits<{ select: [view: ViewType]; toggleTheme: [] }>()
const { t, locale } = useI18n()
const pluginsStore = usePluginsStore()

const items: { id: ViewType; icon: string }[] = [
  { id: 'chat', icon: 'MessageSquare' },
  { id: 'files', icon: 'FolderTree' },
  { id: 'search', icon: 'Search' },
  { id: 'git', icon: 'GitBranch' },
  { id: 'plugins', icon: 'Puzzle' },
  { id: 'community', icon: 'Users' },
  { id: 'settings', icon: 'Settings' },
]

// 统一接口：内置项和插件项共用此类型
interface ActivityBarItem {
  id: string
  icon: string
  _handler?: string
  _pluginName?: string
  _isPlugin?: boolean
  _label?: Record<string, string>
}

// 图标名 → lucide 组件映射表（预导入常用图标，插件声明未知图标时降级为 Puzzle）
const lucideIconMap: Record<string, LucideIcon> = {
  MessageSquare, FolderTree, Search, GitBranch, Puzzle, Users, Settings,
  Zap, Smile, Bell, Star, Heart, AlertCircle,
}

// 固定内置项 + 插件注册的动态项
const allItems = computed<ActivityBarItem[]>(() => {
  const pluginActions: ActivityBarItem[] = (pluginsStore.actions ?? []).map((a: PluginAction) => ({
    id: a.id,
    icon: a.icon,
    _handler: a.handler,
    _pluginName: a.pluginName,
    _isPlugin: true,
    _label: a.label,
  }))
  return [...items, ...pluginActions]
})

function onItemClick(item: any) {
  if (item._isPlugin) {
    // 插件 action：派发事件到总线，不切换 ActivityBar 视图
    pluginEventBus.emit(item._handler, { pluginName: item._pluginName, actionId: item.id })
  } else {
    // 内置 action：切换到对应视图
    emit('select', item.id)
  }
}
</script>

<template>
  <div class="activity-bar">
    <div class="top">
      <button
        v-for="item in allItems"
        :key="item.id"
        class="icon-btn"
        :class="{ active: !item._isPlugin && activeView === item.id }"
        :title="item._isPlugin ? (item._label?.[locale] ?? item._label?.['en'] ?? item._pluginName) : t('activityBar.' + item.id)"
        @click="onItemClick(item)"
      >
        <component :is="lucideIconMap[item.icon] ?? Puzzle" :size="22" />
      </button>
    </div>
    <div class="bottom">
      <button class="icon-btn theme-btn" :title="theme === 'dark' ? t('activityBar.lightMode') : t('activityBar.darkMode')" @click="emit('toggleTheme')">
        <Sun v-if="theme === 'dark'" :size="20" />
        <Moon v-else :size="20" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.activity-bar {
  width: 50px;
  background: var(--bg-secondary);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  flex-shrink: 0;
  border-right: 1px solid var(--border-subtle);
}

.top {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.bottom {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.icon-btn {
  width: 40px;
  height: 40px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition);
}

.icon-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

.icon-btn.active {
  background: var(--accent-muted);
  color: var(--accent);
}
</style>
