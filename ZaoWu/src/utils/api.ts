/**
 * API 路径工具 — 集中管理所有后端接口 URL。
 *
 * 用法:
 *   apiPath('/explorer/projects')  →  '/api/v1/explorer/projects'
 *   wsApiPath('/community/ws')     →  '/api/v1/community/ws'
 *
 * 升级到 v2 时只需修改 API_VERSION 常量即可。
 */

const API_VERSION = '/api/v1'

export function apiPath(path: string): string {
  return `${API_VERSION}${path}`
}

/** WebSocket 路径构建（社区协作） */
export function wsApiPath(endpoint: string): string {
  return `${API_VERSION}${endpoint}`
}
