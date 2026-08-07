<script setup lang="ts">
import { AlertCircle } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { ErrorPayload } from '@/types'

const props = defineProps<{
  error: ErrorPayload
}>()

const emit = defineEmits<{
  /** CTA 点击：透出 action，由父级走 recoveryActions 注册表 */
  action: [action: string]
}>()

const { t } = useI18n()

/** 后端分类器文案为中文硬编码；i18n 映射命中则覆盖（升级期兜底） */
function displayMessage(): string {
  const key = `agent.error.${props.error.code}`
  const localized = t(key)
  if (localized !== key) return localized
  return props.error.message
}
</script>

<template>
  <div class="error-card" role="alert">
    <div class="error-head">
      <AlertCircle :size="14" />
      <span class="error-title">{{ displayMessage() }}</span>
    </div>
    <div class="error-meta">
      <span v-if="error.code" class="meta-item">错误码: {{ error.code }}</span>
      <span v-if="error.traceId" class="meta-item">追踪ID: {{ error.traceId }}</span>
    </div>
    <div v-if="error.recovery && error.recovery.length" class="error-ctas">
      <button
        v-for="(r, i) in error.recovery"
        :key="i"
        class="cta-btn"
        @click="emit('action', r.action)"
      >
        {{ r.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.error-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  margin-top: 8px;
  border: 1px solid var(--danger);
  border-radius: 10px;
  background: var(--bg-glass);
}

.error-head {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--danger);
  font-size: 13px;
  font-weight: 600;
}

.error-title {
  color: var(--text-primary);
  font-weight: 500;
}

.error-meta {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.error-ctas {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.cta-btn {
  padding: 4px 12px;
  border-radius: 6px;
  border: 1px solid var(--border-glass);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition);
}

.cta-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}
</style>
