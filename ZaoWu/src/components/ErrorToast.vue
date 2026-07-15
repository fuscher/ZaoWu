<script setup lang="ts">
import { ref, onMounted } from 'vue'

const props = defineProps<{
  message: string
  type?: 'error' | 'warning' | 'info'
  duration?: number
}>()

const emit = defineEmits<{ close: [] }>()
const visible = ref(false)

onMounted(() => {
  visible.value = true
  setTimeout(() => {
    visible.value = false
    setTimeout(() => emit('close'), 300)
  }, props.duration || 3000)
})
</script>

<template>
  <Transition name="toast">
    <div v-if="visible" class="toast" :class="type || 'error'">
      <span class="toast-text">{{ message }}</span>
    </div>
  </Transition>
</template>

<style scoped>
.toast {
  position: fixed;
  top: 60px;
  right: 16px;
  z-index: 10001;
  padding: 12px 20px;
  border-radius: 8px;
  font-size: 13px;
  box-shadow: var(--shadow-sm);
  max-width: 360px;
}

.toast.error {
  background: var(--danger-bg);
  border: 1px solid var(--danger-border);
  color: var(--danger);
}

.toast.warning {
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  color: var(--warning);
}

.toast.info {
  background: var(--accent-muted);
  border: 1px solid var(--accent-border);
  color: var(--accent);
}

.toast-text {
  word-break: break-word;
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
