<script setup lang="ts">
defineProps<{
  visible: boolean
  progress?: string
}>()
</script>

<template>
  <Teleport to="body">
    <Transition name="overlay">
      <div v-if="visible" class="loading-overlay">
        <div class="loading-content">
          <div class="spinner"></div>
          <span v-if="progress" class="progress-text">{{ progress }}</span>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.loading-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.spinner {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 3px solid transparent;
  border-top-color: var(--text-secondary);
  border-right-color: var(--text-primary);
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.progress-text {
  font-size: 14px;
  color: var(--text-secondary);
}

.overlay-enter-active,
.overlay-leave-active {
  transition: opacity 0.2s ease;
}

.overlay-enter-from,
.overlay-leave-to {
  opacity: 0;
}
</style>
