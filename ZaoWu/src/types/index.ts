export type Theme = 'dark' | 'light'

export type ViewType = 'chat' | 'files' | 'search' | 'git' | 'plugins' | 'community' | 'settings'

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  model?: string
  tokens?: number
}

export interface Conversation {
  id: string
  title: string
  providerId: string
  modelId: string
  systemPrompt: string
  messages: Message[]
  createdAt: string
  updatedAt: string
  messageCount?: number
}

export interface LLMProvider {
  id: string
  name: string
  apiBase: string
  apiKey: string
  models: LLMModel[]
}

export interface LLMModel {
  id: string
  name: string
  contextLength?: number
}

export interface LLMConfig {
  defaultProviderId: string
  defaultModelId: string
  temperature: number
  maxTokens: number
  topP: number
  systemPrompt: string
}

export interface LLMPreset {
  id: string
  name: string
  systemPrompt: string
  temperature: number
  maxTokens: number
  topP: number
}

export interface ViewItem {
  id: ViewType
  label: string
  icon: string
}

export interface BackgroundSettings {
  enabled: boolean
  effect: string
  persist: boolean
  language: string
  theme: string
  searchMaxFileSizeKB: number
  searchResultLimit: number
}

export interface Project {
  id: string
  path: string
  name: string
  addedAt: string
  archived: boolean
  lastModified: string | null
}

export interface TreeNode {
  name: string
  path: string
  type: 'file' | 'directory'
  children?: TreeNode[]
}

export interface SearchResult {
  path: string
  name: string
  matches: SearchMatch[]
}

export type SearchMatch = ContentMatch | FilenameMatch

export interface ContentMatch {
  type: 'content'
  line: number
  content: string
  startIndex: number
  endIndex: number
}

export interface FilenameMatch {
  type: 'filename'
}

declare global {
  interface Window {
    pywebview?: {
      api: {
        minimize: () => void
        maximize: () => void
        restore: () => void
        move: (x: number, y: number) => void
        shutdown: () => void
        select_folder: () => Promise<string | null>
      }
    }
    __SETTINGS__?: Record<string, unknown>
  }
}
