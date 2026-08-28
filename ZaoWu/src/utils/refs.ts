/**
 * S14: @ 引用工具 — 内部标记格式与解析（契约 §0.3）。
 *
 * 内部格式：@{projectId}:relpath（projectId 为项目 uuid；relpath 相对项目根，
 * 正斜杠）。展示格式（浮层/气泡 chip 的 @/name/relpath 视觉前缀）由组件自行映射。
 * 后端只消费 files 数组，禁止从 content 正则解析 —— 本模块负责前端侧
 * 「提取 files + 保留原文标记」的职责边界。
 */
import type { ReferenceFile } from '@/types'

/** 正斜杠归一后的相对路径（剥离项目根前缀） */
export function toRelPath(fullPath: string, projectPath: string): string {
  const normFull = fullPath.replace(/\\/g, '/')
  const normProj = projectPath.replace(/\\/g, '/').replace(/\/+$/, '')
  if (normFull.startsWith(normProj + '/')) {
    return normFull.slice(normProj.length + 1)
  }
  return normFull
}

/** 内部标记：@{projectId}:relpath（唯一可解析格式，不接受仅 name 标记） */
export function referenceMarker(projectId: string, relpath: string): string {
  return `@${projectId}:${relpath}`
}

/** 内部标记正则（全局匹配，用于气泡 chip 渲染/提取） */
export const REFERENCE_TOKEN_RE = /@[^\s:@]+:[^\s]+/g

/** 从消息文本提取引用数组（发送时解析；content 原文保留标记供 chip 渲染） */
export function extractReferences(content: string): ReferenceFile[] {
  const files: ReferenceFile[] = []
  const re = /@([^\s:@]+):([^\s]+)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) {
    files.push({ projectId: m[1]!, path: m[2]! })
  }
  return files
}
