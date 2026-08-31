import { reactive } from 'vue'
import { defineStore } from 'pinia'
import type { BackgroundSettings, AgentIterationTiers } from '@/types'

function detectLanguage(): string {
  const lang = navigator.language || 'en'
  return lang.startsWith('zh') ? 'zh-CN' : 'en'
}

/** S15: 迭代挡位默认映射（低耗/经济/默认/性能/火力；0 = 无限） */
export const AGENT_ITERATION_TIER_DEFAULTS: AgentIterationTiers = {
  low: 15,
  mid: 30,
  std: 60,
  pro: 100,
  max: 0,
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
    autoCheckUpdates: false,
    agentIterationTiers: { ...AGENT_ITERATION_TIER_DEFAULTS },
  }

  const background = reactive<BackgroundSettings>({
    ...defaults,
    ...((window as any).__SETTINGS__ ?? {}),
  })
  // 深度兜底：旧 settings.json 无 agentIterationTiers 时补默认，避免面板读 undefined
  if (!background.agentIterationTiers) {
    background.agentIterationTiers = { ...AGENT_ITERATION_TIER_DEFAULTS }
  }

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

  // S15: 更新单个迭代挡位的轮次数（0 = 无限），随后持久化
  function setAgentIterationTier(key: keyof AgentIterationTiers, value: number) {
    if (!background.agentIterationTiers) {
      background.agentIterationTiers = { ...AGENT_ITERATION_TIER_DEFAULTS }
    }
    const v = Math.max(0, Math.min(300, Math.round(Number(value) || 0)))
    background.agentIterationTiers[key] = v
    persist()
  }

  function resetBg() {
    updateBg({ ...defaults })
  }

  return { background, updateBg, resetBg, setAgentIterationTier }
})
