<script setup lang="ts">
import { useI18n } from '@/i18n'
import ExplorerPanel from './ExplorerPanel.vue'
import SearchPanel from './SearchPanel.vue'
import ConversationList from './ConversationList.vue'
import type { ViewType } from '@/types'

defineProps<{ view: ViewType; collapsed: boolean }>()
const emit = defineEmits<{ toggle: [] }>()
const { t } = useI18n()
</script>

<template>
  <div class="side-panel" :class="{ collapsed }">
    <div class="panel-header">
      <span class="panel-title">
        <template v-if="view === 'chat'">{{ t('sidebar.conversations') }}</template>
        <template v-else-if="view === 'files'">{{ t('sidebar.explorer') }}</template>
        <template v-else-if="view === 'search'">{{ t('sidebar.search') }}</template>
        <template v-else-if="view === 'git'">{{ t('sidebar.sourceControl') }}</template>
        <template v-else-if="view === 'plugins'">{{ t('sidebar.plugins') }}</template>
        <template v-else-if="view === 'community'">{{ t('sidebar.community') }}</template>
        <template v-else-if="view === 'settings'">{{ t('sidebar.settings') }}</template>
      </span>
      <button class="collapse-btn" @click="emit('toggle')">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M10 4L6 8l4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
    <div class="panel-body">
      <template v-if="view === 'chat'">
        <ConversationList />
      </template>
      <template v-else-if="view === 'files'">
        <ExplorerPanel />
      </template>
      <template v-else-if="view === 'search'">
        <SearchPanel />
      </template>
      <template v-else-if="view === 'git'">
        <div class="list-item">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1v7M7 8l-2-2M7 8l2-2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="3.5" cy="11.5" r="1.5" stroke="currentColor" stroke-width="1.2" fill="none"/><circle cx="10.5" cy="11.5" r="1.5" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('sidebar.mainBranch') }}</div>
            <div class="list-desc">{{ t('sidebar.currentBranch') }}</div>
          </div>
        </div>
        <div class="list-item">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M4 7h6M7 4v6" stroke="currentColor" stroke-width="1.2"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('sidebar.changes') }}</div>
            <div class="list-desc">{{ t('sidebar.3uncommitted') }}</div>
          </div>
        </div>
        <div class="list-item">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 12V3h5l2 2v7H3z" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('sidebar.history') }}</div>
            <div class="list-desc">{{ t('sidebar.12commits') }}</div>
          </div>
        </div>
      </template>
      <template v-else-if="view === 'plugins'">
        <div class="list-item">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M4 3v1a2 2 0 004 0V3M3 7h8M7 3v5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><rect x="2.5" y="2.5" width="9" height="9" rx="1.5" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('sidebar.installed') }}</div>
            <div class="list-desc">{{ t('sidebar.2pluginsActive') }}</div>
          </div>
        </div>
        <div class="list-item">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="4" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M7 4v6M4 7h6" stroke="currentColor" stroke-width="1.2"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('sidebar.marketplace') }}</div>
            <div class="list-desc">{{ t('sidebar.browsePlugins') }}</div>
          </div>
        </div>
      </template>
      <template v-else-if="view === 'community'">
        <div class="list-item">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="5" cy="5" r="2.5" stroke="currentColor" stroke-width="1.2"/><path d="M1 12c0-2.5 2-4 4-4s4 1.5 4 4" stroke="currentColor" stroke-width="1.2" fill="none"/><circle cx="10" cy="5" r="2" stroke="currentColor" stroke-width="1.2"/><path d="M9 12c0-2 1.5-3 3-3" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('sidebar.communityHub') }}</div>
            <div class="list-desc">{{ t('sidebar.connectWithOthers') }}</div>
          </div>
        </div>
      </template>
      <template v-else-if="view === 'settings'">
        <div class="list-item">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M7 4v2l1.5 1" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('settings.appearance') }}</div>
            <div class="list-desc">{{ t('settings.theme') }}、{{ t('settings.background') }}、{{ t('settings.language') }}</div>
          </div>
        </div>
        <div class="list-item">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="2" y="3" width="10" height="8" rx="1.5" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M5 7h4M7 5v4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('settings.aiModels') }}</div>
            <div class="list-desc">{{ t('settings.providerManagement') }}</div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.side-panel {
  width: 220px;
  background: var(--bg-tertiary);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: width var(--transition), opacity var(--transition);
  overflow: hidden;
}

.side-panel.collapsed {
  width: 0;
  opacity: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.panel-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.8px;
}

.collapse-btn {
  background: none;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  display: flex;
}

.collapse-btn:hover {
  color: var(--text-secondary);
  background: var(--bg-glass-hover);
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.list-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background var(--transition);
}

.list-item:hover {
  background: var(--bg-glass-hover);
}

.list-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
  display: flex;
}

.list-text {
  min-width: 0;
}

.list-title {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.list-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
