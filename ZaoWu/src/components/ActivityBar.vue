<script setup lang="ts">
import { MessageSquare, FolderTree, Search, GitBranch, Puzzle, Users, Settings, Sun, Moon } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { Theme, ViewType } from '@/types'

defineProps<{ activeView: ViewType; theme: Theme }>()
const emit = defineEmits<{ select: [view: ViewType]; toggleTheme: [] }>()
const { t } = useI18n()

const items: { id: ViewType; icon: string }[] = [
  { id: 'chat', icon: 'MessageSquare' },
  { id: 'files', icon: 'FolderTree' },
  { id: 'search', icon: 'Search' },
  { id: 'git', icon: 'GitBranch' },
  { id: 'plugins', icon: 'Puzzle' },
  { id: 'community', icon: 'Users' },
  { id: 'settings', icon: 'Settings' },
]
</script>

<template>
  <div class="activity-bar">
    <div class="top">
      <button
        v-for="item in items"
        :key="item.id"
        class="icon-btn"
        :class="{ active: activeView === item.id }"
        :title="t('activityBar.' + item.id)"
        @click="emit('select', item.id)"
      >
        <MessageSquare v-if="item.icon === 'MessageSquare'" :size="22" />
        <FolderTree v-if="item.icon === 'FolderTree'" :size="22" />
        <Search v-if="item.icon === 'Search'" :size="22" />
        <GitBranch v-if="item.icon === 'GitBranch'" :size="22" />
        <Puzzle v-if="item.icon === 'Puzzle'" :size="22" />
        <Users v-if="item.icon === 'Users'" :size="22" />
        <Settings v-if="item.icon === 'Settings'" :size="22" />
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
