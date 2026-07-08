<script setup lang="ts">
import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { backgroundRegistry } from './backgrounds/index'

const store = useSettingsStore()

const current = computed(() =>
  backgroundRegistry.find(b => b.meta.id === store.background.effect)
)
</script>

<template>
  <component
    :is="current?.component"
    v-if="current && store.background.enabled"
    v-bind="store.background"
  />
</template>
