/**
 * 阶段 C9: 恢复动作注册表 — 错误卡片 / 完成态 CTA 的 action → handler 映射。
 *
 * action 由后端 ErrorClassifier / done.recovery 携带（对齐 master §3.5.2），
 * 前端在这里把抽象动作绑定到具体行为。未知 action 静默忽略（升级期兼容）。
 */
import type { RecoveryAction } from '@/types'

export interface RecoveryContext {
  /** 最近一条 user message 正文（retry 用） */
  lastUserMessage: string
  /** 切到 build 模式并继续（合成 "请执行上述方案" 重发） */
  switchToBuild: () => void
  /** 打开 Provider 设置面板 */
  openProviders: () => void
  /** 打开模型切换器 */
  openModelSwitcher: () => void
  /** 清空当前对话消息 */
  clearMessages: () => void
  /** 滚动到方案气泡 */
  scrollToPlan: () => void
  /** 重发最近一条 user message */
  retry: () => void
}

export type RecoveryHandler = (ctx: RecoveryContext) => void

const registry: Record<string, RecoveryHandler> = {
  retry: (ctx) => ctx.retry(),
  'switch_preset:build': (ctx) => ctx.switchToBuild(),
  'open:settings:providers': (ctx) => ctx.openProviders(),
  'open:model_switcher': (ctx) => ctx.openModelSwitcher(),
  clear_messages: (ctx) => ctx.clearMessages(),
  scroll_to_plan: (ctx) => ctx.scrollToPlan(),
}

/** 执行一组恢复动作；未知 action 忽略。返回实际执行的数量。 */
export function runRecoveryActions(
  actions: RecoveryAction[] | undefined,
  ctx: RecoveryContext
): number {
  if (!actions || actions.length === 0) return 0
  let executed = 0
  for (const { action } of actions) {
    const handler = registry[action]
    if (handler) {
      handler(ctx)
      executed++
    }
  }
  return executed
}

export function isKnownRecoveryAction(action: string): boolean {
  return action in registry
}
