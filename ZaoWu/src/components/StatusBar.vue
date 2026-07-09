<script setup lang="ts">
import { useI18n } from '@/i18n'

const { t } = useI18n()
const model = 'ZaoWu v0.1.0-xiaoshu'
</script>

<template>
  <div class="status-bar">
    <div class="status-left">
      <span class="status-indicator ready"></span>
      <span class="status-text">{{ t('statusBar.ready') }}</span>
    </div>
    <div class="status-right">
      <span class="model-badge">{{ model }}</span>
    </div>
  </div>
</template>

<style scoped>
.status-bar {
  height: 26px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
  flex-shrink: 0;
}

.status-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-tertiary);
}

.status-indicator.ready {
  background: var(--success);
  box-shadow: 0 0 4px var(--success);
}

.status-text {
  font-size: 11px;
  color: var(--text-tertiary);
}

.status-right {
  display: flex;
  align-items: center;
}

.model-badge {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-glass);
}
</style>
