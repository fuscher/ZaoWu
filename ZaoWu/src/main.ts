import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'

const app = createApp(App)

app.use(createPinia())

app.mount('#app')

// ── 插件系统初始化 ──
// Pinia 安装后、app 挂载后，拉取后端插件列表和前端扩展声明。
// 插件扩展非核心功能，加载失败不阻塞应用启动。
import { usePluginsStore } from './stores/plugins'
const pluginsStore = usePluginsStore()
pluginsStore.fetchPlugins()
pluginsStore.fetchExtensions()
