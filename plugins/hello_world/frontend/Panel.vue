<template>
  <div class="hello-panel">
    <div class="hello-greeting">{{ greeting }}</div>
    <button @click="fetchGreeting" class="hello-btn">刷新 / Refresh</button>
    <div v-if="projects.length" class="hello-projects">
      项目数量：{{ projects.length }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const greeting = ref('Hello, World!')
const projects = ref<any[]>([])

// 从插件自定义 API 获取问候语
async function fetchGreeting() {
  try {
    const res = await fetch('/api/plugins/hello_world/greet')
    const data = await res.json()
    if (data.ok) greeting.value = data.greeting
  } catch { /* ignore */ }
}

// 从插件自定义 API 获取项目列表
async function fetchProjects() {
  try {
    const res = await fetch('/api/plugins/hello_world/projects')
    const data = await res.json()
    if (data.ok) projects.value = data.projects || []
  } catch { /* ignore */ }
}

onMounted(() => {
  fetchGreeting()
  fetchProjects()
})
</script>

<style scoped>
.hello-panel {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hello-greeting {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.hello-btn {
  padding: 6px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--bg-glass);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition);
  align-self: flex-start;
}

.hello-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.hello-projects {
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
