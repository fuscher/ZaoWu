import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import zhCN from './locales/zh-CN.json'
import en from './locales/en.json'

const locales: Record<string, Record<string, unknown>> = {
  'zh-CN': zhCN,
  'en': en,
}

export function useI18n() {
  const store = useSettingsStore()

  const locale = computed(() => locales[store.background.language] ?? locales['en'])

  function t(key: string, params?: Record<string, string | number>): string {
    const currentLocale = locale.value
    const keys = key.split('.')
    let value: unknown = currentLocale
    for (const k of keys) {
      if (value && typeof value === 'object') {
        value = (value as Record<string, unknown>)[k]
      } else {
        return key
      }
    }
    if (typeof value !== 'string') return key

    if (!params) return value

    return value.replace(/\{(\w+)\}/g, (_, name) => {
      return params[name] !== undefined ? String(params[name]) : `{${name}}`
    })
  }

  return { t }
}
