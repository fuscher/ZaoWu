<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from '@/i18n'
import { usePluginsStore } from '@/stores/plugins'
import { PluginHost } from '@/plugin-system'

const { t } = useI18n()
const pluginsStore = usePluginsStore()
const model = 'ZaoWu v0.1.0-xiaoshu'

type ServerStatus = 'checking' | 'ready' | 'offline'

const status = ref<ServerStatus>('checking')
const BACKOFF_MAX = 60
const RETRY_BASE = 10
let failCount = 0
let timerId: ReturnType<typeof setTimeout> | null = null
let abortController: AbortController | null = null

function interval(): number {
  if (status.value === 'ready') return RETRY_BASE * 1000
  const seconds = Math.min(RETRY_BASE * 2 ** failCount, BACKOFF_MAX)
  return seconds * 1000
}

async function check() {
  abortController = new AbortController()
  const timeoutId = setTimeout(() => abortController?.abort(), 5000)

  try {
    const res = await fetch('/api/health', { signal: abortController.signal })
    if (res.ok) {
      status.value = 'ready'
      failCount = 0
    } else {
      status.value = 'offline'
      failCount++
    }
  } catch {
    status.value = 'offline'
    failCount++
  } finally {
    clearTimeout(timeoutId)
    abortController = null
  }
}

function scheduleNext() {
  timerId = setTimeout(async () => {
    await check()
    scheduleNext()
  }, interval())
}

function stop() {
  if (timerId !== null) {
    clearTimeout(timerId)
    timerId = null
  }
  if (abortController) {
    abortController.abort()
    abortController = null
  }
}

function start() {
  stop()
  check().then(() => scheduleNext())
}

function onVisibilityChange() {
  if (document.hidden) {
    stop()
  } else {
    start()
  }
}

onMounted(() => {
  start()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  stop()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="status-bar">
    <div class="status-left">
      <span class="status-indicator" :class="status"></span>
      <span class="status-text">{{ t(`statusBar.${status}`) }}</span>
    </div>
    <div class="status-right">
      <!-- 插件状态栏小部件 -->
      <template v-for="item in pluginsStore.statusItems" :key="item.id">
        <PluginHost
          v-if="item.position === 'right'"
          :plugin-name="item.pluginName"
          :component-name="item.component"
        />
      </template>
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

.status-indicator.offline {
  background: var(--danger);
  box-shadow: 0 0 4px var(--danger);
}

.status-indicator.checking {
  background: var(--warning);
  box-shadow: 0 0 4px var(--warning);
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
