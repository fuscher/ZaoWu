<script setup lang="ts">
import { computed } from 'vue'
import { ClipboardList, Hammer } from '@lucide/vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  preset: 'build' | 'plan'
}>()

const { t } = useI18n()

const badge = computed(() => {
  if (props.preset === 'plan') {
    return {
      icon: ClipboardList,
      label: t('agent.modeBadge.plan'),
      hint: t('agent.modeBadge.planHint'),
      cls: 'plan',
    }
  }
  return {
    icon: Hammer,
    label: t('agent.modeBadge.build'),
    hint: t('agent.modeBadge.buildHint'),
    cls: 'build',
  }
})
</script>

<template>
  <span class="mode-badge" :class="badge.cls" :title="badge.hint">
    <component :is="badge.icon" :size="12" />
    <span>{{ badge.label }}</span>
  </span>
</template>

<style scoped>
.mode-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11.5px;
  white-space: nowrap;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  cursor: help;
}

.mode-badge.plan {
  color: var(--accent);
  border-color: var(--accent-muted);
  background: var(--accent-muted);
}

.mode-badge.build {
  color: var(--text-secondary);
}
</style>
