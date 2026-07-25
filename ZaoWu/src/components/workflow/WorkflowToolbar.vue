<script setup lang="ts">
import { Play, Square, Save, Download, Upload, Activity } from '@lucide/vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  name: string
  isRunning: boolean
}>()

const emit = defineEmits<{
  createBlank: []
  save: []
  toggleInspect: []
  run: []
  stop: []
}>()

const { t } = useI18n()
</script>

<template>
  <header class="workflow-toolbar">
    <div class="toolbar-left">
      <span class="workflow-name">{{ props.name }}</span>
    </div>

    <div class="toolbar-center">
      <button v-if="!props.isRunning" class="tool-btn primary" @click="emit('run')">
        <Play :size="14" />
        <span>{{ t('workflow.run') }}</span>
      </button>
      <button v-else class="tool-btn danger" @click="emit('stop')">
        <Square :size="14" />
        <span>{{ t('workflow.stop') }}</span>
      </button>

      <button class="tool-btn" @click="emit('save')">
        <Save :size="14" />
        <span>{{ t('workflow.save') }}</span>
      </button>
    </div>

    <div class="toolbar-right">
      <button class="tool-btn" @click="emit('createBlank')">
        <Download :size="14" />
        <span>{{ t('workflow.new') }}</span>
      </button>
      <button class="tool-btn" @click="emit('toggleInspect')">
        <Activity :size="14" />
        <span>{{ t('workflow.inspect') }}</span>
      </button>
      <button class="tool-btn" disabled>
        <Upload :size="14" />
        <span>{{ t('workflow.import') }}</span>
      </button>
    </div>
  </header>
</template>

<style scoped>
.workflow-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 44px;
  padding: 0 12px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-subtle);
}

.toolbar-left,
.toolbar-center,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.workflow-name {
  font-size: 13px;
  font-weight: 600;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s;
}

.tool-btn:hover:not(:disabled) {
  background: var(--bg-hover);
}

.tool-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tool-btn.primary {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.tool-btn.danger {
  background: #ef4444;
  color: #fff;
  border-color: #ef4444;
}
</style>
