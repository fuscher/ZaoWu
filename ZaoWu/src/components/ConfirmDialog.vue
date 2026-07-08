<script setup lang="ts">
import { useI18n } from '@/i18n'

defineProps<{
  visible: boolean
  title: string
  message: string
}>()

const emit = defineEmits<{ confirm: []; cancel: [] }>()
const { t } = useI18n()
</script>

<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div v-if="visible" class="dialog-overlay" @click.self="emit('cancel')">
        <div class="dialog-box">
          <div class="dialog-title">{{ title }}</div>
          <div class="dialog-message">{{ message }}</div>
          <div class="dialog-actions">
            <button class="btn btn-cancel" @click="emit('cancel')">{{ t('explorer.cancel') }}</button>
            <button class="btn btn-confirm" @click="emit('confirm')">{{ t('explorer.confirm') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.dialog-box {
  background: var(--bg-secondary);
  border: 1px solid var(--border-glass);
  border-radius: 12px;
  padding: 24px;
  min-width: 320px;
  max-width: 420px;
  box-shadow: var(--shadow);
}

.dialog-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.dialog-message {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 24px;
  line-height: 1.5;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel {
  background: var(--bg-glass);
  color: var(--text-secondary);
}

.btn-cancel:hover {
  background: var(--bg-glass-hover);
}

.btn-confirm {
  background: var(--accent);
  color: #fff;
}

.btn-confirm:hover {
  background: var(--accent-hover);
}

.dialog-enter-active,
.dialog-leave-active {
  transition: opacity 0.2s ease;
}

.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}
</style>
