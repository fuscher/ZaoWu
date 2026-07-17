<template>
  <div class="cau-readme-settings">
    <div class="setting-row">
      <label class="setting-label">{{ t('enable_readme') }}</label>
      <input
        type="checkbox"
        v-model="config.readme_enabled"
        class="setting-checkbox"
        @change="save"
      />
    </div>

    <div class="setting-row setting-row--column">
      <label class="setting-label">{{ t('readme_path') }}</label>
      <input
        v-model="config.readme_path"
        class="setting-input"
        :placeholder="t('readme_path_placeholder')"
        @change="save"
      />
      <span class="setting-hint">{{ t('readme_path_hint') }}</span>
    </div>

    <div class="setting-row">
      <label class="setting-label">{{ t('theme') }}</label>
      <select v-model="config.readme_theme" class="setting-select" @change="save">
        <option value="auto">{{ t('theme_auto') }}</option>
        <option value="dark">{{ t('theme_dark') }}</option>
        <option value="light">{{ t('theme_light') }}</option>
      </select>
    </div>

    <div class="setting-row">
      <label class="setting-label">{{ t('refresh_interval') }}</label>
      <input
        v-model.number="config.readme_refresh_seconds"
        type="number"
        min="5"
        class="setting-input narrow"
        @change="save"
      />
      <span class="setting-unit">{{ t('seconds') }}</span>
    </div>

    <div v-if="saved" class="saved-msg">{{ t('saved') }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePluginsStore } from '@/stores/plugins'

const pluginsStore = usePluginsStore()

interface Config {
  readme_enabled: boolean
  readme_path: string
  readme_theme: string
  readme_refresh_seconds: number
}

const config = ref<Config>({
  readme_enabled: true,
  readme_path: 'README.md',
  readme_theme: 'auto',
  readme_refresh_seconds: 10,
})
const saved = ref(false)

function t(key: string): string {
  const messages: Record<string, string> = {
    enable_readme: '启用 README 展示 / Enable README',
    readme_path: 'README 路径 / README Path',
    readme_path_placeholder: 'README.md',
    readme_path_hint: '相对路径基于插件目录，也可使用绝对路径',
    theme: '主题 / Theme',
    theme_auto: '自动 / Auto',
    theme_dark: '深色 / Dark',
    theme_light: '浅色 / Light',
    refresh_interval: '刷新间隔 / Refresh Interval',
    seconds: '秒 / s',
    saved: '已保存 / Saved',
  }
  return messages[key] ?? key
}

onMounted(async () => {
  await pluginsStore.fetchPlugins()
  const plugin = pluginsStore.plugins.find((p) => p.name === 'code_assistant_utils')
  if (plugin?.config) {
    config.value = {
      readme_enabled: plugin.config.readme_enabled !== false,
      readme_path: plugin.config.readme_path ?? 'README.md',
      readme_theme: plugin.config.readme_theme ?? 'auto',
      readme_refresh_seconds: Math.max(
        5,
        Number(plugin.config.readme_refresh_seconds) || 10,
      ),
    }
  }
})

async function save() {
  await pluginsStore.updateConfig('code_assistant_utils', {
    ...pluginConfig(),
    readme_enabled: config.value.readme_enabled,
    readme_path: config.value.readme_path,
    readme_theme: config.value.readme_theme,
    readme_refresh_seconds: Math.max(5, Number(config.value.readme_refresh_seconds) || 10),
  })
  saved.value = true
  setTimeout(() => {
    saved.value = false
  }, 1500)
}

function pluginConfig(): Record<string, any> {
  const plugin = pluginsStore.plugins.find((p) => p.name === 'code_assistant_utils')
  return plugin?.config ? { ...plugin.config } : {}
}
</script>

<style scoped>
.cau-readme-settings {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.setting-row--column {
  flex-direction: column;
  align-items: stretch;
}

.setting-label {
  font-size: 13px;
  color: var(--text-primary);
  flex-shrink: 0;
}

.setting-input,
.setting-select {
  background: var(--bg-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 13px;
  padding: 6px 10px;
  min-width: 180px;
  outline: none;
  transition: border-color 0.2s var(--transition);
}

.setting-input.narrow {
  min-width: 80px;
}

.setting-input:focus,
.setting-select:focus {
  border-color: var(--accent);
}

.setting-checkbox {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
  cursor: pointer;
}

.setting-unit {
  font-size: 12px;
  color: var(--text-tertiary);
  min-width: 60px;
}

.setting-hint {
  font-size: 12px;
  color: var(--text-tertiary);
}

.saved-msg {
  font-size: 12px;
  color: var(--success);
}
</style>
