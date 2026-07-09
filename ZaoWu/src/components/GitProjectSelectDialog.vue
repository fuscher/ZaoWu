<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { useProjectsStore } from '@/stores/projects'
import type { Project } from '@/types'

const emit = defineEmits<{ close: []; select: [project: Project] }>()
const { t } = useI18n()
const projectsStore = useProjectsStore()

const projects = computed(() => projectsStore.activeProjects)
</script>

<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog">
      <div class="dialog-header">
        <span class="dialog-title">{{ t('git.selectProject') }}</span>
        <button class="dialog-close" @click="emit('close')">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
      </div>
      <div class="dialog-body">
        <div v-if="projects.length === 0" class="dialog-empty">{{ t('git.noProjects') }}</div>
        <div
          v-for="p in projects"
          :key="p.id"
          class="dialog-item"
          @click="emit('select', p)"
        >
          <svg class="dialog-item-icon" width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 3h4l2 2h4v7H2V3z" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span class="dialog-item-name">{{ p.name }}</span>
          <span class="dialog-item-path">{{ p.path }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border-glass);
  border-radius: 12px;
  width: 400px;
  max-height: 60vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.3);
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-subtle);
}

.dialog-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.dialog-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
}

.dialog-close:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.dialog-body {
  padding: 8px;
  overflow-y: auto;
  flex: 1;
}

.dialog-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
}

.dialog-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background var(--transition);
}

.dialog-item:hover {
  background: var(--bg-glass-hover);
}

.dialog-item-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.dialog-item-name {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dialog-item-path {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}
</style>
