import { ref, watch } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import type { Theme } from '@/types'

const theme = ref<Theme>('dark')

export function useTheme() {
  const store = useSettingsStore()

  function applyTheme(t: Theme) {
    document.documentElement.setAttribute('data-theme', t)
  }

  function setTheme(t: Theme) {
    theme.value = t
    applyTheme(t)
    store.updateBg({ theme: t })
  }

  function toggleTheme() {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  const saved = store.background.theme as Theme | undefined
  if (saved === 'light' || saved === 'dark') {
    theme.value = saved
  }
  applyTheme(theme.value)

  watch(theme, applyTheme)

  return { theme, setTheme, toggleTheme }
}
