/**
 * 插件前端组件自动发现与注册。
 *
 * 双轨加载机制：
 * 1. 构建时通过 import.meta.glob 扫描 plugins 目录下的 vue 文件（静态 registry）
 * 2. 运行时通过 /api/plugins/<name>/frontend/_manifest.json 发现后安装的插件，
 *    并通过动态 import() 加载预编译的 JS bundle（运行时 registry）
 *
 * resolvePluginComponent() 先查静态 registry，再查运行时 registry，
 * 最后尝试从后端动态加载。
 */
import { defineAsyncComponent, type Component } from 'vue'

// ── 构建时扫描，静态注册 ─────────────────────────────────────────────
// 使用相对路径：从 src/plugin-system/ 到项目根 plugins/（向上 3 层）
// 注意：import.meta.glob 不支持 @ 别名前缀，必须使用 ./ ../ 或 / 开头
const pluginModules = import.meta.glob('../../../plugins/*/frontend/*.vue')

interface PluginComponentMeta {
  pluginName: string
  componentName: string
  factory: () => Promise<any>
}

// 静态 registry（import.meta.glob 注册的，构建时确定）
const staticRegistry = new Map<string, PluginComponentMeta>()

// 运行时动态注册的组件（安装后发现的）
const runtimeRegistry = new Map<string, PluginComponentMeta>()

// 正在加载中的插件 manifest（防止重复请求）
const manifestCache = new Map<string, Record<string, string>>()

// 正在进行的 bundle 加载 Promise（防止并发重复加载）
const loadingPromises = new Map<string, Promise<void>>()

// 解析路径并注册到静态 registry
for (const path of Object.keys(pluginModules)) {
  const match = path.match(/plugins\/([^/]+)\/frontend\/(.+)\.vue$/)
  if (!match || !match[1] || !match[2]) continue
  const pluginName = match[1]
  const componentName = match[2]
  const key = `${pluginName}:${componentName}`
  staticRegistry.set(key, {
    pluginName,
    componentName,
    factory: pluginModules[path] as () => Promise<any>,
  })
}

/**
 * 从后端加载指定插件的前端 bundle manifest，并注册到运行时 registry。
 * 使用 loadingPromises 防止同一插件的并发加载。
 */
async function loadPluginBundles(pluginName: string): Promise<void> {
  // 已缓存，跳过
  if (manifestCache.has(pluginName)) return

  // 正在加载中，等待同一个 Promise
  const existing = loadingPromises.get(pluginName)
  if (existing) return existing

  const promise = _doLoad(pluginName)
  loadingPromises.set(pluginName, promise)
  try {
    await promise
  } finally {
    loadingPromises.delete(pluginName)
  }
}

async function _doLoad(pluginName: string): Promise<void> {
  try {
    const res = await fetch(`/api/plugins/${pluginName}/frontend/_manifest.json`)
    if (!res.ok) return // 插件没有前端 bundle

    const bundles: Record<string, string> = await res.json()
    manifestCache.set(pluginName, bundles)

    for (const [componentName, bundlePath] of Object.entries(bundles)) {
      const url = `/api/plugins/${pluginName}/frontend/${bundlePath}`
      const key = `${pluginName}:${componentName}`
      runtimeRegistry.set(key, {
        pluginName,
        componentName,
        factory: () => import(/* @vite-ignore */ url),
      })
    }
  } catch {
    // 静默失败 —— 插件前端 bundle 加载失败不应阻塞宿主应用
  }
}

/**
 * 根据插件名和组件名获取异步组件。
 *
 * 查找顺序：
 * 1. 静态 registry（import.meta.glob 注册的，构建时确定）
 * 2. 运行时 registry（已加载过的后安装插件）
 * 3. 尝试从后端动态加载该插件的 bundle manifest
 *
 * 未找到时返回 null，调用方可降级为占位 UI。
 */
export function resolvePluginComponent(
  pluginName: string,
  componentName: string,
): Component | null {
  const key = `${pluginName}:${componentName}`

  // 1. 先查静态 registry
  const staticMeta = staticRegistry.get(key)
  if (staticMeta) return defineAsyncComponent(staticMeta.factory)

  // 2. 再查运行时 registry
  const runtimeMeta = runtimeRegistry.get(key)
  if (runtimeMeta) return defineAsyncComponent(runtimeMeta.factory)

  // 3. 尝试从后端动态加载
  return defineAsyncComponent(async () => {
    await loadPluginBundles(pluginName)
    const meta = runtimeRegistry.get(key) ?? staticRegistry.get(key)
    if (!meta) {
      throw new Error(`Plugin component ${pluginName}:${componentName} not found`)
    }
    return meta.factory()
  })
}

/**
 * 列出所有已注册的插件组件（调试用）。
 */
export function listRegisteredComponents(): string[] {
  return [
    ...Array.from(staticRegistry.keys()),
    ...Array.from(runtimeRegistry.keys()),
  ]
}
