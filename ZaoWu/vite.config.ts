import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      // Plugins live outside ./src; alias their shared deps back to the host node_modules
      // so components like ReadmePanel can import 'markdown-it' without bundling errors.
      'markdown-it': fileURLToPath(new URL('./node_modules/markdown-it/index.mjs', import.meta.url)),
    },
  },
})
