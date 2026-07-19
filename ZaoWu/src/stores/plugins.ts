import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { apiPath } from '@/utils/api'

export interface PluginInfo {
  name: string
  version: string
  description: Record<string, string>
  author: string
  enabled: boolean
  loaded: boolean
  config: Record<string, any>
  error: string | null
}

export interface PluginPanel {
  id: string
  label: Record<string, string>
  icon: string
  component: string
  order: number
  pluginName: string
}

export interface PluginAction {
  id: string
  label: Record<string, string>
  icon: string
  handler: string
  order: number
  pluginName: string
}

export interface PluginStatusItem {
  id: string
  component: string
  position: 'left' | 'right'
  order: number
  pluginName: string
}

export interface PluginSettingsSection {
  id: string
  label: Record<string, string>
  component: string
  icon: string
  order: number
  pluginName: string
}

export interface PluginDetailSection {
  id: string
  label: Record<string, string>
  component: string
  order: number
  pluginName: string
}

export const usePluginsStore = defineStore('plugins', () => {
  // ── 插件列表 ──
  const plugins = ref<PluginInfo[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ── 前端扩展聚合 ──
  const panels = ref<PluginPanel[]>([])
  const actions = ref<PluginAction[]>([])
  const statusItems = ref<PluginStatusItem[]>([])
  const settingsSections = ref<PluginSettingsSection[]>([])
  const detailSections = ref<PluginDetailSection[]>([])

  // ── 计算属性 ──
  const enabledPlugins = computed(() => plugins.value.filter(p => p.enabled))
  const hasPlugins = computed(() => plugins.value.length > 0)

  // ── API 调用 ──

  /** 获取已安装插件列表 */
  async function fetchPlugins() {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(apiPath('/plugins'))
      const data = await res.json()
      if (data.ok) {
        plugins.value = data.plugins ?? []
      } else {
        error.value = data.error ?? 'Failed to fetch plugins'
      }
    } catch (e: any) {
      error.value = e.message ?? 'Failed to fetch plugins'
    } finally {
      loading.value = false
    }
  }

  /** 获取所有已启用插件的前端扩展声明 */
  async function fetchExtensions() {
    try {
      const res = await fetch(apiPath('/plugins/extensions'))
      const data = await res.json()
      if (data.ok) {
        panels.value = (data.panels || []).sort(
          (a: PluginPanel, b: PluginPanel) => a.order - b.order,
        )
        actions.value = (data.actions || []).sort(
          (a: PluginAction, b: PluginAction) => a.order - b.order,
        )
        statusItems.value = (data.statusItems || []).sort(
          (a: PluginStatusItem, b: PluginStatusItem) => a.order - b.order,
        )
        settingsSections.value = (data.settings || []).sort(
          (a: PluginSettingsSection, b: PluginSettingsSection) => a.order - b.order,
        )
        detailSections.value = (data.detailSections || []).sort(
          (a: PluginDetailSection, b: PluginDetailSection) => a.order - b.order,
        )
      }
    } catch {
      // 静默失败 —— 插件扩展非核心功能
    }
  }

  /** 启用插件 */
  async function enablePlugin(name: string) {
    const res = await fetch(apiPath(`/plugins/${name}/enable`), { method: 'POST' })
    const data = await res.json()
    if (data.ok) {
      await fetchPlugins()
      await fetchExtensions()
    }
    return data
  }

  /** 禁用插件 */
  async function disablePlugin(name: string) {
    const res = await fetch(apiPath(`/plugins/${name}/disable`), { method: 'POST' })
    const data = await res.json()
    if (data.ok) {
      await fetchPlugins()
      await fetchExtensions()
    }
    return data
  }

  /** 重载插件 */
  async function reloadPlugin(name: string) {
    const res = await fetch(apiPath(`/plugins/${name}/reload`), { method: 'POST' })
    const data = await res.json()
    if (data.ok) {
      await fetchPlugins()
      await fetchExtensions()
    }
    return data
  }

  /** 卸载插件 */
  async function uninstallPlugin(name: string) {
    const res = await fetch(apiPath(`/plugins/${name}`), { method: 'DELETE' })
    const data = await res.json()
    if (data.ok) {
      await fetchPlugins()
      await fetchExtensions()
    }
    return data
  }

  /** 从 zip 文件安装插件 */
  async function installPlugin(file: File) {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(apiPath('/plugins/install'), { method: 'POST', body: form })
    const data = await res.json()
    if (data.ok) {
      await fetchPlugins()
      await fetchExtensions()
    }
    return data
  }

  /** 更新插件配置 */
  async function updateConfig(name: string, config: Record<string, any>) {
    const res = await fetch(apiPath(`/plugins/${name}/config`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    })
    const data = await res.json()
    if (data.ok) {
      await fetchPlugins()
    }
    return data
  }

  return {
    // 状态
    plugins,
    loading,
    error,
    panels,
    actions,
    statusItems,
    settingsSections,
    detailSections,
    // 计算属性
    enabledPlugins,
    hasPlugins,
    // 方法
    fetchPlugins,
    fetchExtensions,
    enablePlugin,
    disablePlugin,
    reloadPlugin,
    uninstallPlugin,
    installPlugin,
    updateConfig,
  }
})
