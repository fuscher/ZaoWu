<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from '@/i18n'
import BackgroundManager from './BackgroundManager.vue'

const { t } = useI18n()
const emit = defineEmits<{ done: [] }>()
const visible = ref(true)

onMounted(() => {
  setTimeout(() => {
    visible.value = false
    setTimeout(() => emit('done'), 400)
  }, 3000)
})
</script>

<template>
  <Transition name="fade">
    <div v-if="visible" class="loading-screen">
      <BackgroundManager />
      <div class="content">
        <h1 class="title">{{ t('loading.title') }}</h1>
        <p class="subtitle">{{ t('loading.subtitle') }}</p>
        <div class="spinner">
          <div class="ring"></div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.loading-screen {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: var(--splash-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  color: var(--splash-accent);
  -webkit-app-region: no-drag;
}

.content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  position: relative;
  z-index: 1;
}

.title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.5px;
  margin: 0;
}

.subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 32px;
  letter-spacing: 2px;
  text-transform: uppercase;
}

.spinner {
  position: relative;
  width: 32px;
  height: 32px;
}

.ring {
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

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.4s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
