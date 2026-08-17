/**
 * 检查更新 — 全局单例 composable。
 *
 * 所有组件共享同一份响应式状态；首次调用时自动后台检查一次。
 * 后续 checkForUpdates() / startDownload() / applyUpdate() 可由任意组件触发。
 */
import { ref } from 'vue'
import { useI18n } from '@/i18n'
import { useSettingsStore } from '@/stores/settings'

export type UpdateState =
  | 'idle' | 'unsupported' | 'checking' | 'latest'
  | 'available' | 'downloading' | 'ready' | 'applying'

const updateState = ref<UpdateState>('idle')
const currentVersion = ref('')
const latestVersion = ref('')
const updateNotes = ref('')
const updateProgress = ref(0)
let _initialized = false
let _statusPoll: ReturnType<typeof setInterval> | null = null

function stopStatusPoll() {
  if (_statusPoll !== null) {
    clearInterval(_statusPoll)
    _statusPoll = null
  }
}

export function useUpdate() {
  const { t } = useI18n()

  // toast 由调用方注入（SettingsPanel 负责渲染 ErrorToast）
  // 绑定前缓存消息，bindToast 时一次性 flush
  let _showToast: ((msg: string, type: 'error' | 'warning' | 'info') => void) | null = null
  const _pendingToasts: Array<[string, 'error' | 'warning' | 'info']> = []
  function bindToast(fn: (msg: string, type: 'error' | 'warning' | 'info') => void) {
    _showToast = fn
    for (const [msg, type] of _pendingToasts.splice(0)) fn(msg, type)
  }
  function toast(msg: string, type: 'error' | 'warning' | 'info' = 'info') {
    if (_showToast) _showToast(msg, type)
    else _pendingToasts.push([msg, type])
  }

  async function loadVersion() {
    try {
      const res = await fetch('/api/version')
      if (res.ok) {
        const data = await res.json()
        if (data?.version) currentVersion.value = data.version
      }
    } catch {
      // 后端不可达时保持默认显示
    }
  }

  async function consumeUpdateResult() {
    try {
      const res = await fetch('/api/update/check?consume_only=1')
      if (!res.ok) return
      const data = await res.json()
      if (!data.supported) {
        updateState.value = 'unsupported'
        return
      }
      if (data.lastResult === 'ok') {
        toast(t('settings.updateSuccess'), 'info')
      } else if (data.lastResult === 'rolled_back') {
        toast(t('settings.updateFailed'), 'warning')
      }
    } catch {
      // 静默
    }
  }

  async function checkForUpdates() {
    updateState.value = 'checking'
    try {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 15_000)
      let res: Response
      try {
        res = await fetch('/api/update/check', { signal: ctrl.signal })
      } finally {
        clearTimeout(timer)
      }
      if (!res.ok) throw new Error('check failed')
      const data = await res.json()
      if (!data.supported) {
        updateState.value = 'unsupported'
        return
      }
      if (data.error) {
        toast(t('settings.checkFailed'), 'error')
        updateState.value = 'idle'
        return
      }
      if (data.hasUpdate) {
        latestVersion.value = data.latest ?? ''
        updateNotes.value = data.notes ?? ''
        updateState.value = 'available'
      } else {
        toast(t('settings.updateUnavailable'), 'info')
        updateState.value = 'latest'
        setTimeout(() => {
          if (updateState.value === 'latest') updateState.value = 'idle'
        }, 3000)
      }
    } catch {
      toast(t('settings.checkFailed'), 'error')
      updateState.value = 'idle'
    }
  }

  function pollDownloadStatus() {
    stopStatusPoll()
    _statusPoll = setInterval(async () => {
      try {
        const res = await fetch('/api/update/status')
        if (!res.ok) return
        const data = await res.json()
        if (data.state === 'downloading') {
          updateProgress.value = data.progress ?? 0
        } else if (data.state === 'ready') {
          stopStatusPoll()
          updateProgress.value = 100
          updateState.value = 'ready'
        } else if (data.state === 'idle') {
          // error 有值 = 下载失败；无 error = 服务重启导致内存态丢失
          stopStatusPoll()
          if (data.error) toast(t('settings.downloadFailed'), 'error')
          updateProgress.value = 0
          updateState.value = 'available'
        }
      } catch {
        // 轮询失败忽略
      }
    }, 1000)
  }

  async function startDownload() {
    updateState.value = 'downloading'
    updateProgress.value = 0
    try {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 15_000)
      let res: Response
      try {
        res = await fetch('/api/update/download', { signal: ctrl.signal })
      } finally {
        clearTimeout(timer)
      }
      const data = await res.json().catch(() => null)
      if (res.ok && data?.ok) {
        pollDownloadStatus()
        return
      }
      if (data?.error === 'download_in_progress') {
        pollDownloadStatus()
        return
      }
      toast(t('settings.downloadFailed'), 'error')
      updateProgress.value = 0
      updateState.value = 'available'
    } catch {
      toast(t('settings.downloadFailed'), 'error')
      updateProgress.value = 0
      updateState.value = 'available'
    }
  }

  async function applyUpdate() {
    updateState.value = 'applying'
    try {
      const res = await fetch('/api/update/apply', { method: 'POST' })
      const data = await res.json().catch(() => null)
      if (res.ok && data?.ok) return
      throw new Error('apply failed')
    } catch {
      toast(t('settings.applyUnknown'), 'warning')
      updateState.value = 'ready'
    }
  }

  /** 应用启动时调用一次：消费上次结果；若开启自动检查则后台静默检查。 */
  async function initAutoCheck() {
    if (_initialized) return
    _initialized = true
    const settingsStore = useSettingsStore()
    await loadVersion()
    await consumeUpdateResult()
    if (settingsStore.background.autoCheckUpdates) {
      checkForUpdates()
    }
  }

  return {
    // 状态
    updateState,
    currentVersion,
    latestVersion,
    updateNotes,
    updateProgress,
    // 方法
    bindToast,
    loadVersion,
    consumeUpdateResult,
    checkForUpdates,
    startDownload,
    applyUpdate,
    initAutoCheck,
  }
}
