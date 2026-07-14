<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'
import { useProjectsStore } from '@/stores/projects'
import { usePluginsStore } from '@/stores/plugins'
import { PluginHost, pluginEventBus } from '@/plugin-system'
import ExplorerPanel from './ExplorerPanel.vue'
import SearchPanel from './SearchPanel.vue'
import ConversationList from './ConversationList.vue'
import RoomPanel from './RoomPanel.vue'
import GitCommitGraph from './GitCommitGraph.vue'
import GitProjectSelectDialog from './GitProjectSelectDialog.vue'
import GitBranchDialog from './GitBranchDialog.vue'
import GitMissingDialog from './GitMissingDialog.vue'
import GitNoRepoDialog from './GitNoRepoDialog.vue'
import { RefreshCw, PackageOpen, Power, Trash2 } from '@lucide/vue'
import ConfirmDialog from './ConfirmDialog.vue'
import type { ViewType, Project } from '@/types'
import type { PluginInfo } from '@/stores/plugins'

defineProps<{ view: ViewType; collapsed: boolean }>()
const emit = defineEmits<{ toggle: []; highlightSection: [section: string]; showPluginDetail: [pluginName: string] }>()
const { t, locale } = useI18n()
const gitStore = useGitStore()
const projectsStore = useProjectsStore()
const pluginsStore = usePluginsStore()

function getLocalizedLabel(label: Record<string, string>): string {
  return label[locale.value] ?? label['en'] ?? Object.values(label)[0] ?? ''
}

function getLocalizedDescription(plugin: PluginInfo): string {
  return getLocalizedLabel(plugin.description)
}

function confirmUninstall(name: string) {
  uninstallTarget.value = name
}

const uninstallTarget = ref<string | null>(null)
const uninstallConfirmTitle = computed(() => t('plugins.uninstallConfirmTitle'))
const uninstallConfirmMessage = computed(() =>
  t('plugins.uninstallConfirmMessage', { name: uninstallTarget.value ?? '' }),
)

function handleUninstallConfirm() {
  if (uninstallTarget.value) {
    pluginsStore.uninstallPlugin(uninstallTarget.value)
  }
  uninstallTarget.value = null
}

function handleUninstallCancel() {
  uninstallTarget.value = null
}

function handleBannerClick(section: string) {
  emit('highlightSection', section)
}

const showProjectDialog = ref(false)
const showBranchDialog = ref(false)
const showMissingDialog = ref(false)
const showNoRepoDialog = ref(false)
const historyExpanded = ref(false)

const canManageBranch = computed(() => gitStore.selectedProject !== null)
const canViewHistory = computed(() => gitStore.selectedProject !== null && gitStore.hasGitRepo)

async function handleGitTabEnter() {
  if (gitStore.gitAvailable === 'unchecked') {
    const ok = await gitStore.checkGit()
    if (!ok) {
      showMissingDialog.value = true
      return
    }
  } else if (gitStore.gitAvailable === 'unavailable') {
    showMissingDialog.value = true
    return
  }
}

async function handleProjectClick() {
  await gitStore.ensureProjectsLoaded()
  showProjectDialog.value = true
}

function handleProjectSelected(project: Project) {
  showProjectDialog.value = false
  gitStore.selectProject(project)
}

function handleBranchClick() {
  if (!gitStore.selectedProject) return
  if (!gitStore.hasGitRepo) {
    showNoRepoDialog.value = true
    return
  }
  showBranchDialog.value = true
}

function handleBranchSelected(branch: string) {
  showBranchDialog.value = false
  gitStore.switchBranch(branch)
}

function handleHistoryClick() {
  if (!canViewHistory.value) return
  historyExpanded.value = !historyExpanded.value
  if (historyExpanded.value && gitStore.commits.length === 0) {
    gitStore.fetchCommits(0)
  }
}

async function handleInitRepo() {
  showNoRepoDialog.value = false
  await gitStore.initRepo()
}

watch(() => gitStore.gitAvailable, (val) => {
  if (val === 'unchecked' && showMissingDialog.value) return
})

watch(
  () => projectsStore.projects,
  () => {
    if (!gitStore.selectedProject) return
    const stillExists = projectsStore.activeProjects.find(
      (p) => p.id === gitStore.selectedProject!.id,
    )
    if (!stillExists) {
      gitStore.clearProject()
      historyExpanded.value = false
    }
  },
  { deep: true },
)
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
        <!-- Card 1: Manage Project -->
        <div
          class="list-item git-card"
          :class="{ disabled: false }"
          @click="handleProjectClick"
          :title="t('git.manageProject')"
        >
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 3h4l2 2h4v7H2V3z" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('git.manageProject') }}</div>
            <div class="list-desc">{{ gitStore.selectedProject ? t('git.selectedProject', { name: gitStore.selectedProject.name }) : t('git.selectedProject', { name: '--' }) }}</div>
          </div>
        </div>

        <!-- Card 2: Manage Branch -->
        <div
          class="list-item git-card"
          :class="{ disabled: !canManageBranch }"
          @click="handleBranchClick"
          :title="!canManageBranch ? t('git.noProject') : t('git.manageBranch')"
        >
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1v7M7 8l-2-2M7 8l2-2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="3.5" cy="11.5" r="1.5" stroke="currentColor" stroke-width="1.2" fill="none"/><circle cx="10.5" cy="11.5" r="1.5" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('git.manageBranch') }}</div>
            <div class="list-desc">{{ gitStore.currentBranch ? t('git.currentBranch', { name: gitStore.currentBranch }) : '--' }}</div>
          </div>
        </div>

        <!-- Card 3: History -->
        <div
          class="list-item git-card"
          :class="{ disabled: !canViewHistory }"
          @click="handleHistoryClick"
          :title="!gitStore.selectedProject ? t('git.noProject') : (!gitStore.hasGitRepo ? t('git.noGitRepo') : t('git.history'))"
        >
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M7 3v4l3 2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('git.history') }}</div>
            <div class="list-desc">{{ gitStore.commitCount > 0 ? t('git.commitCount', { count: gitStore.commitCount }) : (gitStore.hasGitRepo ? t('git.commitCount', { count: 0 }) : '--') }}</div>
          </div>
        </div>

        <!-- Expanded Commit Graph -->
        <div v-if="historyExpanded && canViewHistory" class="git-history-container">
          <div class="git-history-header">
            <button class="git-refresh-btn" :title="t('git.refresh')" @click.stop="gitStore.reloadCommits()">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M10 6a4 4 0 11-1-3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><path d="M9 2v3H6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
          </div>
          <GitCommitGraph
            :commits="gitStore.commits"
            :has-more="gitStore.commitsHasMore"
            @load-more="gitStore.loadMoreCommits()"
          />
        </div>
      </template>
      <template v-else-if="view === 'plugins'">
        <!-- 插件管理区域 -->
        <div class="plugin-management">
          <div class="plugin-section-header">
            <span>{{ t('plugins.installed') }}</span>
            <button @click="pluginsStore.fetchPlugins()" class="icon-btn-sm" :title="t('plugins.refresh')">
              <RefreshCw :size="14" />
            </button>
          </div>

          <!-- 加载中 -->
          <div v-if="pluginsStore.loading" class="plugin-loading">{{ t('plugins.loading') }}</div>

          <!-- 空状态 -->
          <div v-else-if="!pluginsStore.hasPlugins" class="plugin-empty">
            <PackageOpen :size="32" />
            <span>{{ t('plugins.noPlugins') }}</span>
          </div>

          <!-- 插件列表 -->
          <div
            v-for="plugin in pluginsStore.plugins"
            :key="plugin.name"
            class="plugin-item"
            :class="{ disabled: !plugin.enabled, broken: !!plugin.error }"
            @click="emit('showPluginDetail', plugin.name)"
          >
            <div class="plugin-item-header">
              <span class="plugin-name">{{ plugin.name }}</span>
              <span class="plugin-version">v{{ plugin.version }}</span>
            </div>
            <div class="plugin-description">{{ getLocalizedDescription(plugin) }}</div>
            <div class="plugin-item-actions">
              <button
                v-if="plugin.enabled"
                @click.stop="pluginsStore.disablePlugin(plugin.name)"
                class="plugin-btn disable"
                :title="t('plugins.disable')"
              >
                <Power :size="12" />
              </button>
              <button
                v-else
                @click.stop="pluginsStore.enablePlugin(plugin.name)"
                class="plugin-btn enable"
                :title="t('plugins.enable')"
              >
                <Power :size="12" />
              </button>
              <button
                @click.stop="pluginsStore.reloadPlugin(plugin.name)"
                class="plugin-btn"
                :title="t('plugins.reload')"
              >
                <RefreshCw :size="12" />
              </button>
              <button
                @click.stop="confirmUninstall(plugin.name)"
                class="plugin-btn danger"
                :title="t('plugins.uninstall')"
              >
                <Trash2 :size="12" />
              </button>
            </div>
            <div v-if="plugin.error" class="plugin-error">{{ plugin.error }}</div>
          </div>
        </div>

        <!-- 插件注册的侧栏面板 -->
        <template v-for="panel in pluginsStore.panels" :key="panel.id">
          <div class="plugin-panel-section">
            <div class="plugin-section-header">
              <span>{{ getLocalizedLabel(panel.label) }}</span>
            </div>
            <PluginHost :plugin-name="panel.pluginName" :component-name="panel.component" />
          </div>
        </template>
      </template>
      <template v-else-if="view === 'community'">
        <RoomPanel />
      </template>
      <template v-else-if="view === 'settings'">
        <div class="list-item" @click="handleBannerClick('appearance')">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M7 4v2l1.5 1" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('settings.appearanceBannerTitle') }}</div>
            <div class="list-desc">{{ t('settings.appearanceBannerDesc') }}</div>
          </div>
        </div>
        <div class="list-item" @click="handleBannerClick('ai-models')">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="2" y="3" width="10" height="8" rx="1.5" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M5 7h4M7 5v4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('settings.aiModelsBannerTitle') }}</div>
            <div class="list-desc">{{ t('settings.aiModelsBannerDesc') }}</div>
          </div>
        </div>
        <div class="list-item" @click="handleBannerClick('community')">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M4 3.5a2 2 0 100 4 2 2 0 000-4zM10 3.5a2 2 0 100 4 2 2 0 000-4zM4 8.5a2 2 0 100 4 2 2 0 000-4z" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('settings.communityBannerTitle') }}</div>
            <div class="list-desc">{{ t('settings.communityBannerDesc') }}</div>
          </div>
        </div>
        <div class="list-item" @click="handleBannerClick('plugins')">
          <div class="list-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1L2 4v6l5 3 5-3V4L7 1z" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>
          </div>
          <div class="list-text">
            <div class="list-title">{{ t('settings.pluginsBannerTitle') }}</div>
            <div class="list-desc">{{ t('settings.pluginsBannerDesc') }}</div>
          </div>
        </div>
      </template>
    </div>
  </div>

  <GitProjectSelectDialog
    v-if="showProjectDialog"
    @close="showProjectDialog = false"
    @select="handleProjectSelected"
  />
  <GitBranchDialog
    v-if="showBranchDialog"
    @close="showBranchDialog = false"
    @select="handleBranchSelected"
  />
  <GitMissingDialog
    v-if="showMissingDialog"
    @close="showMissingDialog = false"
  />
  <GitNoRepoDialog
    v-if="showNoRepoDialog"
    @close="showNoRepoDialog = false"
    @init="handleInitRepo"
  />
  <ConfirmDialog
    :visible="uninstallTarget !== null"
    :title="uninstallConfirmTitle"
    :message="uninstallConfirmMessage"
    @confirm="handleUninstallConfirm"
    @cancel="handleUninstallCancel"
  />
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

.git-card {
  cursor: pointer;
}

.git-card.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.git-history-container {
  margin: 4px 8px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  overflow: hidden;
}

.git-history-header {
  display: flex;
  justify-content: flex-end;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border-subtle);
}

.git-refresh-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
}

.git-refresh-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

/* ── 插件管理 ── */

.plugin-management {
  margin-bottom: 12px;
}

.plugin-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.icon-btn-sm {
  background: none;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  display: flex;
}

.icon-btn-sm:hover {
  color: var(--text-secondary);
  background: var(--bg-glass-hover);
}

.plugin-loading {
  padding: 16px;
  text-align: center;
  font-size: 12px;
  color: var(--text-tertiary);
}

.plugin-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.plugin-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background var(--transition);
  margin: 2px 0;
}

.plugin-item:hover {
  background: var(--bg-glass-hover);
}

.plugin-item.disabled {
  opacity: 0.5;
}

.plugin-item.broken {
  border: 1px solid var(--danger);
}

.plugin-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.plugin-name {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 500;
}

.plugin-version {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 1px 6px;
  border-radius: 4px;
}

.plugin-description {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.plugin-item-actions {
  display: flex;
  gap: 4px;
  margin-top: 2px;
}

.plugin-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition);
}

.plugin-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.plugin-btn.danger:hover {
  background: var(--danger-muted, rgba(255, 80, 80, 0.12));
  color: var(--danger);
}

.plugin-error {
  font-size: 10px;
  color: var(--danger);
  padding: 2px 0;
}

.plugin-panel-section {
  margin-top: 8px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 8px;
}
</style>
