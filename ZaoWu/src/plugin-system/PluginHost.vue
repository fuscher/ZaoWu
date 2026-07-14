<template>
  <Suspense>
    <component v-if="resolvedComponent" :is="resolvedComponent" />
    <div v-else class="plugin-component-missing">
      <span>{{ pluginName }}:{{ componentName }}</span>
    </div>
  </Suspense>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { resolvePluginComponent } from './loader'

const props = defineProps<{
  pluginName: string
  componentName: string
}>()

const resolvedComponent = computed(() =>
  resolvePluginComponent(props.pluginName, props.componentName),
)
</script>

<style scoped>
.plugin-component-missing {
  padding: 8px 12px;
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  border: 1px dashed var(--border-subtle);
  border-radius: 6px;
  text-align: center;
}
</style>
