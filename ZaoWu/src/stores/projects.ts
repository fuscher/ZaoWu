import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { Project } from '@/types'
import { apiPath } from '@/utils/api'

export const useProjectsStore = defineStore('projects', () => {
  const projects = ref<Project[]>([])
  const virtualProjects = ref<Project[]>([])
  const batchMode = ref(false)
  const batchSelected = ref<Set<string>>(new Set())

  const activeProjects = computed(() => [
    ...projects.value.filter(p => !p.archived),
    ...virtualProjects.value,
  ])

  const archivedProjects = computed(() =>
    projects.value.filter(p => p.archived)
  )

  async function fetchProjects() {
    try {
      const res = await fetch(apiPath('/explorer/projects'))
      const data = await res.json()
      if (data.projects) {
        projects.value = data.projects
      }
    } catch {
      // ignore
    }
  }

  async function addProject(path: string): Promise<{ ok: boolean; error?: string }> {
    try {
      const res = await fetch(apiPath('/explorer/add-project'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      })
      const data = await res.json()
      if (data.ok) {
        await fetchProjects()
        return { ok: true }
      }
      return { ok: false, error: data.error }
    } catch (err) {
      console.error('addProject failed', err)
      return { ok: false, error: err instanceof Error ? err.message : 'network error' }
    }
  }

  async function archiveProject(projectId: string): Promise<boolean> {
    try {
      const res = await fetch(apiPath('/explorer/archive-project'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId }),
      })
      const data = await res.json()
      if (data.ok) {
        await fetchProjects()
        return true
      }
      return false
    } catch {
      return false
    }
  }

  async function unarchiveProject(projectId: string): Promise<boolean> {
    try {
      const res = await fetch(apiPath('/explorer/unarchive-project'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId }),
      })
      const data = await res.json()
      if (data.ok) {
        await fetchProjects()
        return true
      }
      return false
    } catch {
      return false
    }
  }

  async function unloadProject(projectId: string): Promise<boolean> {
    try {
      const res = await fetch(apiPath('/explorer/unload-project'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId }),
      })
      const data = await res.json()
      if (data.ok) {
        await fetchProjects()
        return true
      }
      return false
    } catch {
      return false
    }
  }

  async function deleteProject(projectId: string): Promise<boolean> {
    try {
      const res = await fetch(apiPath('/explorer/delete-project'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId }),
      })
      const data = await res.json()
      if (data.ok) {
        await fetchProjects()
        return true
      }
      return false
    } catch {
      return false
    }
  }

  async function batchArchive(): Promise<{ ok: boolean; results: any[] }> {
    const ids = Array.from(batchSelected.value)
    try {
      const res = await fetch(apiPath('/explorer/batch-archive'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectIds: ids }),
      })
      const data = await res.json()
      await fetchProjects()
      return { ok: data.ok, results: data.results || [] }
    } catch {
      return { ok: false, results: [] }
    }
  }

  async function batchUnload(): Promise<{ ok: boolean; results: any[] }> {
    const ids = Array.from(batchSelected.value)
    try {
      const res = await fetch(apiPath('/explorer/batch-unload'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectIds: ids }),
      })
      const data = await res.json()
      await fetchProjects()
      return { ok: data.ok, results: data.results || [] }
    } catch {
      return { ok: false, results: [] }
    }
  }

  async function batchDelete(): Promise<{ ok: boolean; results: any[] }> {
    const ids = Array.from(batchSelected.value)
    try {
      const res = await fetch(apiPath('/explorer/batch-delete'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectIds: ids }),
      })
      const data = await res.json()
      await fetchProjects()
      return { ok: data.ok, results: data.results || [] }
    } catch {
      return { ok: false, results: [] }
    }
  }

  function enterBatchMode() {
    batchMode.value = true
    batchSelected.value = new Set()
  }

  function exitBatchMode() {
    batchMode.value = false
    batchSelected.value = new Set()
  }

  function toggleBatchSelect(projectId: string) {
    if (batchSelected.value.has(projectId)) {
      batchSelected.value.delete(projectId)
    } else {
      batchSelected.value.add(projectId)
    }
  }

  function injectVirtualProject(roomId: string, projectPath: string, projectName: string) {
    if (virtualProjects.value.some(p => p.roomId === roomId)) return
    virtualProjects.value.push({
      id: `virtual-${roomId}`,
      path: projectPath,
      name: projectName,
      addedAt: new Date().toISOString(),
      archived: false,
      lastModified: null,
      virtual: true,
      roomId,
    })
  }

  function removeVirtualProject(roomId: string) {
    virtualProjects.value = virtualProjects.value.filter(p => p.roomId !== roomId)
  }

  return {
    projects,
    virtualProjects,
    batchMode,
    batchSelected,
    activeProjects,
    archivedProjects,
    fetchProjects,
    addProject,
    archiveProject,
    unarchiveProject,
    unloadProject,
    deleteProject,
    batchArchive,
    batchUnload,
    batchDelete,
    enterBatchMode,
    exitBatchMode,
    toggleBatchSelect,
    injectVirtualProject,
    removeVirtualProject,
  }
})
