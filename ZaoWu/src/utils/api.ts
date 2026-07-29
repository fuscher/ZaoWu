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

/** Build an absolute API URL for a project.
 *
 * Local projects use a relative URL (same origin) because the app runs a local
 * backend. Virtual collaboration projects are served by the host's backend on
 * the LAN, so we must route the request to http://<hostAddress>.
 */
export function apiPathForProject(
  project: { virtual?: boolean; hostAddress?: string } | null | undefined,
  path: string,
): string {
  if (project?.virtual && project.hostAddress) {
    return `http://${project.hostAddress}${apiPath(path)}`
  }
  return apiPath(path)
}

/** WebSocket 路径构建（社区协作） */
export function wsApiPath(endpoint: string): string {
  return `${API_VERSION}${endpoint}`
}
