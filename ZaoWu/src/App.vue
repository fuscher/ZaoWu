<script setup lang="ts">
import { ref, watchEffect, onMounted } from 'vue'
import { useTheme } from '@/composables/useTheme'
import { useI18n } from '@/i18n'
import LoadingScreen from '@/components/LoadingScreen.vue'
import MainLayout from '@/components/MainLayout.vue'
import { fetchProviders } from '@/services/ai'
import { listWorkflows } from '@/services/workflow'

const { theme, toggleTheme } = useTheme()
const { t } = useI18n()
const loading = ref(true)
const progress = ref('')

watchEffect(() => {
  document.title = t('loading.title')
})

function onLoadingDone() {
  loading.value = false
}

onMounted(async () => {
  const startTime = performance.now()
  const MIN_DURATION_MS = 3000

  progress.value = t('loading.preparing')

  const initTasks = [
    fetchProviders().catch(() => []),
    listWorkflows().catch(() => []),
  ]

  try {
    progress.value = t('loading.loadingProviders')
    await Promise.all(initTasks)
    progress.value = t('loading.ready')
  } catch {
    progress.value = t('loading.ready')
  }

  const elapsed = performance.now() - startTime
  const remaining = Math.max(0, MIN_DURATION_MS - elapsed)

  setTimeout(() => {
    loading.value = false
  }, remaining)
})
</script>

<template>
  <LoadingScreen v-if="loading" :progress="progress" @done="onLoadingDone" />
  <MainLayout v-else :theme="theme" @toggle-theme="toggleTheme" />
</template>

<style>
@import '@/styles/theme.css';

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  height: 100%;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  background: var(--bg-primary);
  color: var(--text-primary);
  -webkit-app-region: no-drag;
}

#app {
  height: 100%;
  -webkit-app-region: no-drag;
}

::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--scrollbar);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-hover);
}
</style>
