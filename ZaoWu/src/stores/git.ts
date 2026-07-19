import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { Project, GitAvailability, GitBranch, GitChange, GitCommit } from '@/types'
import { useProjectsStore } from './projects'
import { apiPath } from '@/utils/api'

export const useGitStore = defineStore('git', () => {
  const gitAvailable = ref<GitAvailability>('unchecked')
  const selectedProject = ref<Project | null>(null)
  const currentBranch = ref('')
  const branches = ref<GitBranch[]>([])
  const untrackedChanges = ref<GitChange[]>([])
  const stagedChanges = ref<GitChange[]>([])
  const commits = ref<GitCommit[]>([])
  const commitsOffset = ref(0)
  const commitsHasMore = ref(false)
  const commitCount = ref(0)
  const terminalCwd = ref('')
  const isLoading = ref(false)
  const isCommitting = ref(false)
  const hasRepo = ref(false)

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
    stagedChanges.value = []
    commits.value = []
    commitsOffset.value = 0
    commitsHasMore.value = false
    commitCount.value = 0

    const res = await _api<{ ok?: boolean; hasRepo?: boolean; branch?: string; changes?: GitChange[]; error?: string }>('/status')
    if (res.error) return

    if (!res.hasRepo) {
      hasRepo.value = false
      return
    }

    hasRepo.value = true
    currentBranch.value = res.branch || ''
    const changes = res.changes || []
    untrackedChanges.value = changes.filter(c => c.status === 'unstaged')
    stagedChanges.value = changes.filter(c => c.status === 'staged')
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
      untrackedChanges.value = changes.filter(c => c.status === 'unstaged')
      stagedChanges.value = changes.filter(c => c.status === 'staged')
    }
  }

  async function stageFiles(files: string[]): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/stage', { files })
    if (res.ok) await fetchChanges()
    return { ok: !!res.ok, error: res.error }
  }

  async function stageAll(): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/stage-all')
    if (res.ok) await fetchChanges()
    return { ok: !!res.ok, error: res.error }
  }

  async function discardFiles(files: string[]): Promise<{ ok: boolean; error?: string }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string }>('/discard', { files })
    if (res.ok) await fetchChanges()
    return { ok: !!res.ok, error: res.error }
  }

  async function commit(message: string): Promise<{ ok: boolean; error?: string; hash?: string }> {
    if (!selectedProject.value) return { ok: false }
    isCommitting.value = true
    try {
      const res = await _api<{ ok?: boolean; error?: string; hash?: string }>('/commit', { message })
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
    return { ok: !!res.ok, error: res.error, output: res.output }
  }

  async function pull(): Promise<{ ok: boolean; error?: string; output?: string; hasConflicts?: boolean; conflictFiles?: string[] }> {
    if (!selectedProject.value) return { ok: false }
    const res = await _api<{ ok?: boolean; error?: string; output?: string; hasConflicts?: boolean; conflictFiles?: string[] }>('/pull')
    if (res.ok) {
      await fetchChanges()
      await reloadCommits()
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
    stagedChanges.value = []
    commits.value = []
    commitsOffset.value = 0
    commitsHasMore.value = false
    commitCount.value = 0
    hasRepo.value = false
    terminalCwd.value = ''
  }

  return {
    gitAvailable,
    selectedProject,
    currentBranch,
    branches,
    untrackedChanges,
    stagedChanges,
    commits,
    commitsOffset,
    commitsHasMore,
    commitCount,
    terminalCwd,
    isLoading,
    isCommitting,
    hasRepo,
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
    stageFiles,
    stageAll,
    discardFiles,
    commit,
    push,
    pull,
    initRepo,
    undoCommit,
    resetFile,
    execTerminalCmd,
    clearProject,
  }
})
