// 最小化事件总线，用于插件 action handler 字符串 → 前端回调的映射
type Handler = (payload: any) => void

class PluginEventBus {
  private handlers = new Map<string, Set<Handler>>()

  on(event: string, handler: Handler) {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set())
    this.handlers.get(event)!.add(handler)
  }

  off(event: string, handler: Handler) {
    this.handlers.get(event)?.delete(handler)
  }

  emit(event: string, payload?: any) {
    this.handlers.get(event)?.forEach(h => h(payload))
  }
}

export const pluginEventBus = new PluginEventBus()
