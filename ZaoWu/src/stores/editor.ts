import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export const useEditorStore = defineStore('editor', () => {
  const openFilePath = ref<string | null>(null)
  const fileName = ref('')
  const fileContent = ref('')
  const originalContent = ref('')
  const isLoading = ref(false)
  const error = ref('')

  /** Callback invoked after a successful save. Set by collaboration composable to bridge file_diff. */
  const onFileSaved = ref<((path: string, content: string) => void) | null>(null)

  const isDirty = computed(() => fileContent.value !== originalContent.value)

  async function openFile(path: string) {
    openFilePath.value = path
    fileName.value = path.replace(/\\/g, '/').split('/').pop() || path
    isLoading.value = true
    error.value = ''

    try {
      const res = await fetch(`/api/explorer/read-file?path=${encodeURIComponent(path)}`)
      const data = await res.json()
      if (data.ok) {
        fileContent.value = data.content
        originalContent.value = data.content
      } else {
        error.value = data.error || 'failed to read file'
        openFilePath.value = null
      }
    } catch {
      error.value = 'network error'
      openFilePath.value = null
    } finally {
      isLoading.value = false
    }
  }

  function updateContent(content: string) {
    fileContent.value = content
  }

  async function saveFile() {
    if (!openFilePath.value || !isDirty.value) return

    try {
      const res = await fetch('/api/explorer/save-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: openFilePath.value, content: fileContent.value }),
      })
      const data = await res.json()
      if (data.ok) {
        originalContent.value = fileContent.value
        // Bridge to collaboration: notify the collaboration composable to broadcast file_diff
        if (onFileSaved.value) {
          onFileSaved.value(openFilePath.value, fileContent.value)
        }
      } else {
        error.value = data.error || 'failed to save'
      }
    } catch {
      error.value = 'network error'
    }
  }

  /** Reload the current file from disk (used when a remote file_diff is received). */
  async function reloadCurrentFile() {
    if (!openFilePath.value) return
    isLoading.value = true
    error.value = ''
    try {
      const res = await fetch(`/api/explorer/read-file?path=${encodeURIComponent(openFilePath.value)}`)
      const data = await res.json()
      if (data.ok) {
        fileContent.value = data.content
        originalContent.value = data.content
      } else {
        error.value = data.error || 'failed to reload file'
      }
    } catch {
      error.value = 'network error'
    } finally {
      isLoading.value = false
    }
  }

  function revertFile() {
    fileContent.value = originalContent.value
  }

  function closeFile() {
    openFilePath.value = null
    fileName.value = ''
    fileContent.value = ''
    originalContent.value = ''
    error.value = ''
  }

  return {
    openFilePath,
    fileName,
    fileContent,
    originalContent,
    isLoading,
    error,
    isDirty,
    onFileSaved,
    openFile,
    updateContent,
    saveFile,
    reloadCurrentFile,
    revertFile,
    closeFile,
  }
})
