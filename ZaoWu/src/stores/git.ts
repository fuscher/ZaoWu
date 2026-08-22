import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { Project, GitAvailability, GitBranch, GitChange, GitCommit } from '@/types'
import { useProjectsStore } from './projects'
import { apiPath } from '@/utils/api'

interface GitFetchInfo {
  ahead: number
  behind: number
  commits: string[]
}

interface GitStash {
  index: number
  message: string
}

export const useGitStore = defineStore('git', () => {
  const gitAvailable = ref<GitAvailability>('unchecked')
  const selectedProject = ref<Project | null>(null)
  const currentBranch = ref('')
  const branches = ref<GitBranch[]>([])
  const untrackedChanges = ref<GitChange[]>([])
  const unstagedChanges = ref<GitChange[]>([])
  const stagedChanges = ref<GitChange[]>([])
  const conflictChanges = ref<GitChange[]>([])
  const commits = ref<GitCommit[]>([])
  const commitsOffset = ref(0)
  const commitsHasMore = ref(false)
  const commitCount = ref(0)
  const terminalCwd = ref('')
  const isLoading = ref(false)
  const isCommitting = ref(false)
  const hasRepo = ref(false)
  const fetchInfo = ref<GitFetchInfo>({ ahead: 0, behind: 0, commits: [] })
  const isSyncing = ref(false)
  const stashList = ref<GitStash[]>([])

  const hasProject = computed(() => selectedProject.value !== null)
  const hasGitRepo = computed(() => hasRepo.value)

  async function _api<T>(endpoint: string, body?: Record<string, unknown>): Promise<T> {
    const res = await fetch(apiPath('/git') + endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: selectedProject.value?.path, ...body }),
    })
    return res.json() as T
  }

  async function ensureProjectsLoaded() {
    const projectsStore = useProjectsStore()
    if (projectsStore.projects.length === 0) {
      await projectsStore.fetchProjects()
    }
  }

  async function checkGit(): Promise<boolean> {
    try {
      const res = await fetch(apiPath('/git/check'), { method: 'POST' })
      const data = await res.json()
      gitAvailable.value = data.available ? 'available' : 'unavailable'
      return data.available
    } catch {
      gitAvailable.value = 'unavailable'
      return false
    }
  }

  async function selectProject(project: Project) {
    selectedProject.value = project
    terminalCwd.value = project.path
    currentBranch.value = ''
    branches.value = []
    untrackedChanges.value = []
    unstagedChanges.value = []
    stagedChanges.value = []
    conflictChanges.value = []
    commits.value = []
    commitsOffset.value = 0
    commitsHasMore.value = false
    commitCount.value = 0
    fetchInfo.value = { ahead: 0, behind: 0, commits: [] }
    stashList.value = []

    const res = await _api<{ ok?: boolean; hasRepo?: boolean; branch?: string; changes?: GitChange[]; error?: string }>('/status')
    if (res.error) return { error: res.error }

    if (!res.hasRepo) {
      hasRepo.value = false
      return
    }

    hasRepo.value = true
    currentBranch.value = res.branch || ''
    const changes = res.changes || []
    untrackedChanges.value = changes.filter(c => c.status === 'untracked')
    unstagedChanges.value = changes.filter(c => c.status === 'unstaged')
    stagedChanges.value = changes.filter(c => c.status === 'staged')
    conflictChanges.value = changes.filter(c => c.status === 'conflict')
  }

  async function fetchBranches() {
    if (!selectedProject.value) return
    const res = await _api<{ ok?: boolean; branches?: GitBranch[]; error?: string }>('/branches')
    if (res.ok) {
      branches.value = res.branches || []
    }
  }

  async function switchBranch(branch: string): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false, error: 'no project' }
    const res = await _api<{ ok?: boolean; error?: string }>('/switch-branch', { branch })
    if (res.ok) {
      currentBranch.value = branch
      await selectProject(selectedProject.value)
    }
    return { ok: !!res.ok, error: res.error }
  }

  async function fetchCommits(offset: number) {
    if (!selectedProject.value) return
    commitsOffset.value = offset
    const res = await _api<{ ok?: boolean; commits?: GitCommit[]; hasMore?: boolean; error?: string }>(
      '/commits', { limit: 20, offset },
    )
    if (res.ok) {
      commits.value = res.commits || []
      commitsHasMore.value = res.hasMore || false
      commitCount.value = (res.commits || []).length
    }
  }

  async function loadMoreCommits() {
    if (!selectedProject.value || !commitsHasMore.value) return
    const nextOffset = commitsOffset.value + 20
    const res = await _api<{ ok?: boolean; commits?: GitCommit[]; hasMore?: boolean }>(
      '/commits', { limit: 20, offset: nextOffset },
    )
    if (res.ok) {
      commits.value = [...commits.value, ...(res.commits || [])]
      commitsOffset.value = nextOffset
      commitsHasMore.value = res.hasMore || false
      commitCount.value = commits.value.length
    }
  }

  async function reloadCommits() {
    await fetchCommits(0)
  }

  async function fetchChanges() {
    if (!selectedProject.value) return
    const res = await _api<{ ok?: boolean; changes?: GitChange[]; branch?: string; error?: string }>('/status')
    if (res.ok) {
      currentBranch.value = res.branch || ''
      const changes = res.changes || []
      untrackedChanges.value = changes.filter(c => c.status === 'untracked')
      unstagedChanges.value = changes.filter(c => c.status === 'unstaged')
      stagedChanges.value = changes.filter(c => c.status === 'staged')
      conflictChanges.value = changes.filter(c => c.status === 'conflict')
    }
  }

  async function fetchRemote(): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    isSyncing.value = true
    try {
      const res = await _api<{ ok?: boolean; ahead?: number; behind?: number; commits?: string[]; error?: string }>('/fetch')
      if (res.ok) {
        fetchInfo.value = {
          ahead: res.ahead || 0,
          behind: res.behind || 0,
          commits: res.commits || [],
        }
      }
      return { ok: !!res.ok, error: res.error }
    } finally {
      isSyncing.value = false
    }
  }

  async function stageFiles(files: string[]): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/stage', { files })
    if (res.ok) await fetchChanges()
    return { ok: !!res.ok, error: res.error }
  }

  async function unstageFiles(files: string[]): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/unstage', { files })
    if (res.ok) await fetchChanges()
    return { ok: !!res.ok, error: res.error }
  }

  async function stageAll(): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/stage-all')
    if (res.ok) await fetchChanges()
    return { ok: !!res.ok, error: res.error }
  }

  async function discardFiles(files: string[], includeUntracked = false): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/discard', { files, includeUntracked })
    if (res.ok) await fetchChanges()
    return { ok: !!res.ok, error: res.error }
  }

  async function commit(message: string, amend = false): Promise<{ ok: boolean; error?: string; hash?: string }> {
    if (!selectedProject.value) return { ok: false }
    isCommitting.value = true
    try {
      const res = await _api<{ ok?: boolean; error?: string; hash?: string }>('/commit', { message, amend })
      if (res.ok) {
        await fetchChanges()
        await reloadCommits()
      }
      return { ok: !!res.ok, error: res.error, hash: res.hash }
    } finally {
      isCommitting.value = false
    }
  }

  async function push(): Promise<{ ok: boolean; error?: string; output?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string; output?: string }>('/push')
    if (res.ok) await fetchRemote()
    return { ok: !!res.ok, error: res.error, output: res.output }
  }

  async function pull(strategy: 'merge' | 'rebase' = 'merge'): Promise<{ ok: boolean; error?: string; output?: string; hasConflicts?: boolean; conflictFiles?: string[] }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string; output?: string; hasConflicts?: boolean; conflictFiles?: string[] }>('/pull', { strategy })
    if (res.ok) {
      await fetchChanges()
      await reloadCommits()
      await fetchRemote()
    }
    return { ok: !!res.ok, error: res.error, output: res.output, hasConflicts: res.hasConflicts, conflictFiles: res.conflictFiles }
  }

  async function initRepo(): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/init')
    if (res.ok) {
      hasRepo.value = true
      await selectProject(selectedProject.value)
    }
    return { ok: !!res.ok, error: res.error }
  }

  async function undoCommit(): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/undo-commit')
    if (res.ok) {
      await fetchChanges()
      await reloadCommits()
    }
    return { ok: !!res.ok, error: res.error }
  }

  async function resetFile(file: string): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/reset-file', { file })
    if (res.ok) await fetchChanges()
    return { ok: !!res.ok, error: res.error }
  }

  async function stash(message?: string): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/stash', { message })
    if (res.ok) {
      await fetchChanges()
      await reloadCommits()
      await fetchStashes()
    }
    return { ok: !!res.ok, error: res.error }
  }

  async function stashPop(index = 0): Promise<{ ok: boolean; error?: string; hasConflicts?: boolean }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string; hasConflicts?: boolean }>('/stash-pop', { index })
    if (res.ok || res.hasConflicts) {
      await fetchChanges()
      await reloadCommits()
      await fetchStashes()
    }
    return { ok: !!res.ok, error: res.error, hasConflicts: res.hasConflicts }
  }

  async function stashApply(index = 0): Promise<{ ok: boolean; error?: string; hasConflicts?: boolean }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string; hasConflicts?: boolean }>('/stash-apply', { index })
    if (res.ok || res.hasConflicts) {
      await fetchChanges()
      await fetchStashes()
    }
    return { ok: !!res.ok, error: res.error, hasConflicts: res.hasConflicts }
  }

  async function stashDrop(index: number): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/stash-drop', { index })
    return { ok: !!res.ok, error: res.error }
  }

  async function fetchStashes(): Promise<void> {
    if (!selectedProject.value) return
    const res = await _api<{ ok?: boolean; stashes?: GitStash[] }>('/stash-list')
    if (res.ok) {
      stashList.value = res.stashes || []
    }
  }

  async function createBranch(name: string, switchTo = false): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/create-branch', { name, switch: switchTo })
    if (res.ok) {
      await fetchBranches()
      if (switchTo) {
        currentBranch.value = name
        await fetchChanges()
        await reloadCommits()
      }
    }
    return { ok: !!res.ok, error: res.error }
  }

  async function deleteBranch(name: string, force = false): Promise<{ ok: boolean; error?: string; protected?: boolean }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string; protected?: boolean }>('/delete-branch', { name, force })
    if (res.ok) {
      await fetchBranches()
    }
    return { ok: !!res.ok, error: res.error, protected: res.protected }
  }

  async function resolveAcceptOurs(files: string[]): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/resolve-accept-ours', { files })
    if (res.ok) await fetchChanges()
    return { ok: !!res.ok, error: res.error }
  }

  async function resolveAcceptTheirs(files: string[]): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/resolve-accept-theirs', { files })
    if (res.ok) await fetchChanges()
    return { ok: !!res.ok, error: res.error }
  }

  async function execTerminalCmd(command: string): Promise<string> {
    try {
      const res = await fetch(apiPath('/terminal/exec'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cwd: terminalCwd.value, command }),
      })
      const data = await res.json()
      if (data.ok) return data.output || ''
      return data.error || 'command failed'
    } catch {
      return 'network error'
    }
  }

  function clearProject() {
    selectedProject.value = null
    currentBranch.value = ''
    branches.value = []
    untrackedChanges.value = []
    unstagedChanges.value = []
    stagedChanges.value = []
    conflictChanges.value = []
    commits.value = []
    commitsOffset.value = 0
    commitsHasMore.value = false
    commitCount.value = 0
    hasRepo.value = false
    terminalCwd.value = ''
    fetchInfo.value = { ahead: 0, behind: 0, commits: [] }
    stashList.value = []
  }

  async function getFileDiff(file?: string, staged = false): Promise<{ ok: boolean; diff?: string; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; diff?: string; error?: string }>('/diff', { file, staged })
    return { ok: !!res.ok, diff: res.diff, error: res.error }
  }

  async function fetchRemotes(): Promise<{ ok: boolean; remotes?: Array<{name: string; url: string; type: string}>; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; remotes?: Array<{name: string; url: string; type: string}>; error?: string }>('/remote-list')
    return { ok: !!res.ok, remotes: res.remotes, error: res.error }
  }

  async function addRemote(name: string, url: string): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/remote-add', { name, url })
    return { ok: !!res.ok, error: res.error }
  }

  async function removeRemote(name: string): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/remote-remove', { name })
    return { ok: !!res.ok, error: res.error }
  }

  async function fetchTags(): Promise<{ ok: boolean; tags?: string[]; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; tags?: string[]; error?: string }>('/tags')
    return { ok: !!res.ok, tags: res.tags, error: res.error }
  }

  async function createTag(name: string, message?: string): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/create-tag', { name, message })
    return { ok: !!res.ok, error: res.error }
  }

  async function cloneRepository(url: string, dest: string): Promise<{ ok: boolean; path?: string; error?: string }> {
    const res = await _api<{ ok?: boolean; path?: string; error?: string }>('/clone', { url, dest })
    return { ok: !!res.ok, path: res.path, error: res.error }
  }

  return {
    gitAvailable,
    selectedProject,
    currentBranch,
    branches,
    untrackedChanges,
    unstagedChanges,
    stagedChanges,
    conflictChanges,
    commits,
    commitsOffset,
    commitsHasMore,
    commitCount,
    terminalCwd,
    isLoading,
    isCommitting,
    hasRepo,
    fetchInfo,
    isSyncing,
    stashList,
    hasProject,
    hasGitRepo,
    ensureProjectsLoaded,
    checkGit,
    selectProject,
    fetchBranches,
    switchBranch,
    fetchCommits,
    loadMoreCommits,
    reloadCommits,
    fetchChanges,
    fetchRemote,
    stageFiles,
    unstageFiles,
    stageAll,
    discardFiles,
    commit,
    push,
    pull,
    initRepo,
    undoCommit,
    resetFile,
    stash,
    stashPop,
    stashApply,
    stashDrop,
    fetchStashes,
    createBranch,
    deleteBranch,
    resolveAcceptOurs,
    resolveAcceptTheirs,
    getFileDiff,
    fetchRemotes,
    addRemote,
    removeRemote,
    fetchTags,
    createTag,
    cloneRepository,
    execTerminalCmd,
    clearProject,
  }
})
