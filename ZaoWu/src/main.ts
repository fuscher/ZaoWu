import { createApp } from 'vue'
import * as Vue from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'

// 暴露 Vue 实例到全局，供运行时安装的插件 bundle 使用
// 插件 bundle 通过 window.__zaoWu_vue 获取 Vue，避免重复打包
;(window as any).__zaoWu_vue = Vue

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
