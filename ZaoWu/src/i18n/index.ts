import { useSettingsStore } from '@/stores/settings'
import zhCN from './locales/zh-CN.json'
import en from './locales/en.json'

const locales: Record<string, Record<string, unknown>> = {
  'zh-CN': zhCN,
  'en': en,
}

export function useI18n() {
  const store = useSettingsStore()

  function t(key: string): string {
    const locale = locales[store.background.language] ?? locales['en']
    const keys = key.split('.')
    let value: unknown = locale
    for (const k of keys) {
      if (value && typeof value === 'object') {
        value = (value as Record<string, unknown>)[k]
      } else {
        return key
      }
    }
    return typeof value === 'string' ? value : key
  }

  return { t }
}
