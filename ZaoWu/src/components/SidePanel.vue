<script setup lang="ts">
import { useSettingsStore } from '@/stores/settings'
import { backgroundRegistry } from './backgrounds/index'
import { useI18n } from '@/i18n'
import ExplorerPanel from './ExplorerPanel.vue'
import SearchPanel from './SearchPanel.vue'
import type { ViewType } from '@/types'

defineProps<{ view: ViewType; collapsed: boolean }>()
const emit = defineEmits<{ toggle: [] }>()
const store = useSettingsStore()
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
        <div class="list-item">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.2"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('sidebar.gettingStarted') }}</div>
            <div class="list-desc">{{ t('sidebar.welcomeAgent') }}</div>
          </div>
        </div>
        <div class="list-item">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.2"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('sidebar.projectSetup') }}</div>
            <div class="list-desc">{{ t('sidebar.configureWorkspace') }}</div>
          </div>
        </div>
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
        <div class="settings-group">
          <div class="setting-row">
            <span class="setting-label">{{ t('settings.background') }}</span>
            <label class="toggle">
              <input type="checkbox" :checked="store.background.enabled" @change="store.updateBg({ enabled: !store.background.enabled })" />
              <span class="toggle-slider"></span>
            </label>
          </div>

            <div class="setting-row">
              <span class="setting-label">{{ t('settings.effect') }}</span>
              <select
                class="setting-select"
                :value="store.background.effect"
                @change="store.updateBg({ effect: ($event.target as HTMLSelectElement).value })"
              >
                <option v-for="bg in backgroundRegistry" :key="bg.meta.id" :value="bg.meta.id">
                  {{ t('backgrounds.' + bg.meta.id) }}
                </option>
              </select>
            </div>

            <div class="setting-row">
              <span class="setting-label">{{ t('settings.language') }}</span>
              <select
                class="setting-select"
                :value="store.background.language"
                @change="store.updateBg({ language: ($event.target as HTMLSelectElement).value })"
              >
                <option value="zh-CN">中文</option>
                <option value="en">English</option>
              </select>
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

.search-box {
  position: relative;
  margin: 8px;
}

.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
}

.search-input {
  width: 100%;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 8px 10px 8px 32px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.search-input::placeholder {
  color: var(--text-tertiary);
}

.search-input:focus {
  border-color: var(--accent);
}

.settings-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 8px;
}

.setting-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.setting-label {
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 64px;
  flex-shrink: 0;
}

.setting-select {
  flex: 1;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 6px;
  padding: 4px 8px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
}

.setting-select:focus {
  border-color: var(--accent);
}

.setting-select option {
  background: var(--bg-primary);
  color: var(--text-primary);
}

.toggle {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
  flex-shrink: 0;
}

.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: var(--bg-glass);
  border-radius: 10px;
  transition: all var(--transition);
  border: 1px solid var(--border-glass);
}

.toggle-slider::before {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  left: 2px;
  bottom: 2px;
  background: var(--text-tertiary);
  border-radius: 50%;
  transition: all var(--transition);
}

.toggle input:checked + .toggle-slider {
  background: var(--accent-muted);
  border-color: var(--accent);
}

.toggle input:checked + .toggle-slider::before {
  background: var(--accent);
  transform: translateX(16px);
}
</style>
