/**
 * 插件前端组件自动发现与注册。
 *
 * 构建时通过 import.meta.glob 扫描 plugins 目录下的 vue 文件，
 * 运行时提供 resolvePluginComponent() 供 PluginHost.vue 动态渲染。
 *
 * 设计参考：components/backgrounds/index.ts 的注册表模式。
 */
import { defineAsyncComponent, type Component } from 'vue'

// 构建时扫描，运行时按需加载
// 使用相对路径：从 src/plugin-system/ 到项目根 plugins/（向上 3 层）
// 注意：import.meta.glob 不支持 @ 别名前缀，必须使用 ./ ../ 或 / 开头
const pluginModules = import.meta.glob('../../../plugins/*/frontend/*.vue')

interface PluginComponentMeta {
  pluginName: string
  componentName: string
  factory: () => Promise<any>
}

// 全局注册表
const registry = new Map<string, PluginComponentMeta>()

// 解析路径并注册
for (const path of Object.keys(pluginModules)) {
  const match = path.match(/plugins\/([^/]+)\/frontend\/(.+)\.vue$/)
  if (!match || !match[1] || !match[2]) continue
  const pluginName = match[1]
  const componentName = match[2]
  const key = `${pluginName}:${componentName}`
  registry.set(key, {
    pluginName,
    componentName,
    factory: pluginModules[path] as () => Promise<any>,
  })
}

/**
 * 根据插件名和组件名获取异步组件。
 * 未找到时返回 null，调用方可降级为占位 UI。
 */
export function resolvePluginComponent(
  pluginName: string,
  componentName: string,
): Component | null {
  const key = `${pluginName}:${componentName}`
  const meta = registry.get(key)
  if (!meta) return null
  return defineAsyncComponent(meta.factory)
}

/**
 * 列出所有已注册的插件组件（调试用）。
 */
export function listRegisteredComponents(): string[] {
  return Array.from(registry.keys())
}
