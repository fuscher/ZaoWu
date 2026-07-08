export type Theme = 'dark' | 'light'

export type ViewType = 'chat' | 'files' | 'search' | 'git' | 'plugins' | 'community' | 'settings'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
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
}
