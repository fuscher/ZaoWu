import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import type { SearchResult } from '@/types'
import { apiPath } from '@/utils/api'

export const useSearchStore = defineStore('search', () => {
  const query = ref('')
  const results = ref<SearchResult[]>([])
  const isSearching = ref(false)
  const totalFiles = ref(0)
  const totalMatches = ref(0)

  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  watch(query, (newQuery) => {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }

    if (!newQuery.trim()) {
      results.value = []
      totalFiles.value = 0
      totalMatches.value = 0
      return
    }

    debounceTimer = setTimeout(() => {
      search()
    }, 300)
  })

  async function search() {
    if (!query.value.trim()) return

    isSearching.value = true
    try {
      const res = await fetch(apiPath('/search'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.value.trim() }),
      })
      const data = await res.json()
      if (data.ok) {
        results.value = data.results || []
        totalFiles.value = data.totalFiles || 0
        totalMatches.value = data.totalMatches || 0
      }
    } catch {
      results.value = []
      totalFiles.value = 0
      totalMatches.value = 0
    } finally {
      isSearching.value = false
    }
  }

  async function cancelSearch() {
    try {
      await fetch(apiPath('/search/cancel'), { method: 'POST' })
    } catch {
      // ignore
    }
  }

  function clearResults() {
    query.value = ''
    results.value = []
    totalFiles.value = 0
    totalMatches.value = 0
  }

  return {
    query,
    results,
    isSearching,
    totalFiles,
    totalMatches,
    search,
    cancelSearch,
    clearResults,
  }
})
