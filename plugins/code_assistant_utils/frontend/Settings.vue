<template>
  <div class="cau-settings">
    <div class="setting-row">
      <label class="setting-label">
        {{ t('default_timezone') }}
      </label>
      <select v-model="config.default_timezone" class="setting-select" @change="save">
        <option value="local">{{ t('local_time') }}</option>
        <option value="utc">UTC</option>
      </select>
    </div>

    <div class="setting-row setting-row--column">
      <label class="setting-label">
        {{ t('exclude_patterns') }}
      </label>
      <textarea
        v-model="excludeText"
        class="setting-textarea"
        rows="6"
        :placeholder="t('exclude_patterns_placeholder')"
        @change="save"
      />
      <span class="setting-hint">{{ t('one_per_line') }}</span>
    </div>

    <div v-if="saved" class="saved-msg">{{ t('saved') }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { usePluginsStore } from '@/stores/plugins'

const pluginsStore = usePluginsStore()

interface Config {
  default_timezone: string
  default_exclude_patterns: string[]
}

const config = ref<Config>({
  default_timezone: 'local',
  default_exclude_patterns: [],
})
const saved = ref(false)

const excludeText = computed({
  get: () => config.value.default_exclude_patterns.join('\n'),
  set: (value: string) => {
    config.value.default_exclude_patterns = value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
  },
})

function t(key: string): string {
  const messages: Record<string, string> = {
    default_timezone: '默认时区 / Default Timezone',
    local_time: '本地时间 / Local',
    exclude_patterns: '默认排除目录 / Default Exclude Patterns',
    exclude_patterns_placeholder: 'node_modules\n.git\n__pycache__',
    one_per_line: '每行一个目录名，用于代码行数统计时过滤',
    saved: '已保存 / Saved',
  }
  return messages[key] ?? key
}

onMounted(async () => {
  await pluginsStore.fetchPlugins()
  const plugin = pluginsStore.plugins.find((p) => p.name === 'code_assistant_utils')
  if (plugin?.config) {
    config.value = {
      default_timezone: plugin.config.default_timezone ?? 'local',
      default_exclude_patterns: plugin.config.default_exclude_patterns ?? [],
    }
  }
})

async function save() {
  await pluginsStore.updateConfig('code_assistant_utils', {
    default_timezone: config.value.default_timezone,
    default_exclude_patterns: config.value.default_exclude_patterns,
  })
  saved.value = true
  setTimeout(() => {
    saved.value = false
  }, 1500)
}
</script>

<style scoped>
.cau-settings {
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

.setting-select,
.setting-textarea {
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

.setting-textarea {
  min-width: auto;
  resize: vertical;
  font-family: var(--font-mono, monospace);
}

.setting-select:focus,
.setting-textarea:focus {
  border-color: var(--accent);
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
