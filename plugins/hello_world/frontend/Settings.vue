<template>
  <div class="hello-settings">
    <div class="setting-row">
      <label>Greeting / 问候语</label>
      <input v-model="greeting" @change="save" class="setting-input" />
    </div>
    <div class="setting-row">
      <label>Log on startup / 启动时记录日志</label>
      <input type="checkbox" v-model="logOnStartup" @change="save" />
    </div>
    <div v-if="saved" class="saved-msg">配置已保存 / Saved</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePluginsStore } from '@/stores/plugins'

const pluginsStore = usePluginsStore()
const greeting = ref('')
const logOnStartup = ref(false)
const saved = ref(false)

onMounted(async () => {
  await pluginsStore.fetchPlugins()
  const p = pluginsStore.plugins.find(p => p.name === 'hello_world')
  if (p) {
    greeting.value = p.config.greeting ?? ''
    logOnStartup.value = p.config.logOnStartup ?? false
  }
})

async function save() {
  await pluginsStore.updateConfig('hello_world', {
    greeting: greeting.value,
    logOnStartup: logOnStartup.value,
  })
  saved.value = true
  setTimeout(() => { saved.value = false }, 1500)
}
</script>

<style scoped>
.hello-settings {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.setting-row label {
  font-size: 13px;
  color: var(--text-primary);
}

.setting-input {
  background: var(--bg-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 13px;
  padding: 4px 8px;
  width: 180px;
}

.setting-input:focus {
  outline: none;
  border-color: var(--accent);
}

.saved-msg {
  font-size: 12px;
  color: var(--success);
}
</style>
