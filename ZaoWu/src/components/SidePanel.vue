<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'
import { useProjectsStore } from '@/stores/projects'
import ExplorerPanel from './ExplorerPanel.vue'
import SearchPanel from './SearchPanel.vue'
import ConversationList from './ConversationList.vue'
import GitCommitGraph from './GitCommitGraph.vue'
import GitProjectSelectDialog from './GitProjectSelectDialog.vue'
import GitBranchDialog from './GitBranchDialog.vue'
import GitMissingDialog from './GitMissingDialog.vue'
import GitNoRepoDialog from './GitNoRepoDialog.vue'
import type { ViewType, Project } from '@/types'

defineProps<{ view: ViewType; collapsed: boolean }>()
const emit = defineEmits<{ toggle: [] }>()
const { t } = useI18n()
const gitStore = useGitStore()
const projectsStore = useProjectsStore()

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
</style>
