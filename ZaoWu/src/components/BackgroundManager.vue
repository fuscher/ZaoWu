<script setup lang="ts">
import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { backgroundRegistry } from './backgrounds/index'

const store = useSettingsStore()

const current = computed(() =>
  backgroundRegistry.find(b => b.meta.id === store.background.effect)
)

const mergedProps = computed(() => {
  const bg = backgroundRegistry.find(b => b.meta.id === store.background.effect)
  return { ...bg?.meta.defaultParams, ...store.background }
})
</script>

<template>
  <component
    :is="current?.component"
    v-if="current && store.background.enabled"
    v-bind="mergedProps"
  />
</template>
