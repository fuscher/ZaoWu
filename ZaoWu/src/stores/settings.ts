import { reactive } from 'vue'
import { defineStore } from 'pinia'
import type { BackgroundSettings } from '@/types'

function detectLanguage(): string {
  const lang = navigator.language || 'en'
  return lang.startsWith('zh') ? 'zh-CN' : 'en'
}

export const useSettingsStore = defineStore('settings', () => {
  const defaults: BackgroundSettings = {
    enabled: true,
    effect: 'silk',
    persist: false,
    language: detectLanguage(),
    theme: 'dark',
    startupView: 'chat',
    searchMaxFileSizeKB: 1024,
    searchResultLimit: 500,
    communityMaxUsers: 5,
    communityDefaultRole: 'collaborator',
    communityFileSizeLimitKB: 512,
    communityInactiveTimeoutMinutes: 120,
  }

  const background = reactive<BackgroundSettings>({
    ...defaults,
    ...((window as any).__SETTINGS__ ?? {}),
  })

  async function persist() {
    const payload: Record<string, unknown> = {}
    for (const key of Object.keys(defaults) as (keyof BackgroundSettings)[]) {
      payload[key] = background[key]
    }
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
    } catch {
      // ignore
    }
  }

  function updateBg(params: Partial<BackgroundSettings>) {
    Object.assign(background, params)
    persist()
  }

  function resetBg() {
    updateBg({ ...defaults })
  }

  return { background, updateBg, resetBg }
})
