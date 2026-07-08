<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from '@/i18n'

declare const window: Window & {
  pywebview?: {
    api: {
      minimize: () => void
      maximize: () => void
      restore: () => void
      move: (x: number, y: number) => void
      shutdown: () => void
    }
  }
}

const { t } = useI18n()

const isClosing = ref(false)
const showClosing = ref(false)
const isMaximized = ref(false)
const isDragging = ref(false)
let dragStartX = 0
let dragStartY = 0
let winStartX = 0
let winStartY = 0

function checkMaximized(): boolean {
  return Math.abs(window.innerWidth - screen.availWidth) < 10
}

function onResize() {
  isMaximized.value = checkMaximized()
}

onMounted(() => {
  isMaximized.value = checkMaximized()
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
})

function onTitleBarMouseDown(e: MouseEvent) {
  if (e.target instanceof HTMLElement && e.target.closest('.window-controls')) return
  if (isMaximized.value) return
  isDragging.value = true
  dragStartX = e.screenX
  dragStartY = e.screenY
  winStartX = window.screenX
  winStartY = window.screenY
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
}

function onDragMove(e: MouseEvent) {
  if (!isDragging.value || !window.pywebview) return
  const dx = e.screenX - dragStartX
  const dy = e.screenY - dragStartY
  window.pywebview.api.move(winStartX + dx, winStartY + dy)
}

function onDragEnd() {
  isDragging.value = false
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
}

function minimize() {
  window.pywebview?.api.minimize()
}

function toggleMaximize() {
  if (isMaximized.value) {
    window.pywebview?.api.restore()
  } else {
    window.pywebview?.api.maximize()
  }
  isMaximized.value = !isMaximized.value
}

function safeClose() {
  if (isClosing.value) return
  isClosing.value = true
    showClosing.value = true
    if (window.pywebview) {
      window.pywebview.api.shutdown()
    }
}
</script>

<template>
  <div class="title-bar" @mousedown="onTitleBarMouseDown">
    <div class="spacer"></div>
    <div class="window-controls">
      <button class="ctrl-btn minimize" :title="t('titleBar.minimize')" @click="minimize">
        <svg width="12" height="12" viewBox="0 0 12 12"><path d="M2 6h8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      </button>
      <button class="ctrl-btn maximize" :title="isMaximized ? t('titleBar.restore') : t('titleBar.maximize')" @click="toggleMaximize">
        <svg v-if="!isMaximized" width="12" height="12" viewBox="0 0 12 12"><rect x="2" y="2" width="8" height="8" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>
        <svg v-else width="12" height="12" viewBox="0 0 12 12"><rect x="1.5" y="3.5" width="7" height="7" stroke="currentColor" stroke-width="1.3" fill="none" opacity="0.4"/><rect x="3.5" y="1.5" width="7" height="7" stroke="currentColor" stroke-width="1.3" fill="none"/></svg>
      </button>
      <button class="ctrl-btn close" :title="t('titleBar.close')" @click="safeClose">
        <svg width="12" height="12" viewBox="0 0 12 12"><path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      </button>
    </div>
  </div>
  <div v-if="showClosing" class="closing-overlay">
    <div class="closing-spinner">
      <div class="closing-ring"></div>
    </div>
    <span class="closing-text">{{ t('titleBar.closing') }}</span>
  </div>
</template>

<style scoped>
.closing-overlay {
  position: fixed;
  inset: 0;
  z-index: 99999;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(4px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.closing-spinner {
  width: 32px;
  height: 32px;
}

.closing-ring {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 3px solid transparent;
  border-top-color: var(--text-secondary);
  border-right-color: var(--text-primary);
  animation: closing-spin 0.8s linear infinite;
}

@keyframes closing-spin {
  to { transform: rotate(360deg); }
}

.closing-text {
  font-size: 15px;
  color: var(--text-secondary);
  letter-spacing: 1px;
}
.title-bar {
  height: 44px;
  display: flex;
  align-items: center;
  padding: 0 12px;
  user-select: none;
  flex-shrink: 0;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-subtle);
}

.spacer {
  flex: 1;
}

.window-controls {
  display: flex;
  align-items: center;
  gap: 4px;
}

.ctrl-btn {
  width: 36px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.ctrl-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

.ctrl-btn.close:hover {
  background: #ff5f56;
  color: #fff;
}

.ctrl-btn.minimize:hover {
  background: #ffbd2e;
  color: #1a1a1e;
}

.ctrl-btn.maximize:hover {
  background: #27c93f;
  color: #fff;
}
</style>
