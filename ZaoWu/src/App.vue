<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import { useTheme } from '@/composables/useTheme'
import { useI18n } from '@/i18n'
import LoadingScreen from '@/components/LoadingScreen.vue'
import MainLayout from '@/components/MainLayout.vue'

const { theme, toggleTheme } = useTheme()
const { t } = useI18n()
const loading = ref(true)

watchEffect(() => {
  document.title = t('loading.title')
})

function onLoadingDone() {
  loading.value = false
}
</script>

<template>
  <LoadingScreen v-if="loading" @done="onLoadingDone" />
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
