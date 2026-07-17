<template>
  <div class="plugin-detail">
    <!-- 头部 -->
    <div class="detail-header">
      <h2>{{ plugin?.name ?? t('plugins.selectPlugin') }}</h2>
      <span v-if="plugin" class="detail-version">v{{ plugin.version }}</span>
    </div>

    <!-- 空状态 -->
    <div v-if="!plugin" class="detail-empty">
      {{ t('plugins.selectHint') }}
    </div>

    <!-- 插件详情 -->
    <template v-else>
      <!-- 基本信息 -->
      <section class="detail-section">
        <h3>{{ t('plugins.info') }}</h3>
        <div class="detail-row">
          <span class="label">{{ t('plugins.author') }}</span>
          <span>{{ plugin.author }}</span>
        </div>
        <div class="detail-row">
          <span class="label">{{ t('plugins.status') }}</span>
          <span :class="plugin.enabled ? 'status-on' : 'status-off'">
            {{ plugin.enabled ? t('plugins.enabled') : t('plugins.disabled') }}
          </span>
        </div>
        <div v-if="plugin.error" class="detail-error">{{ plugin.error }}</div>
      </section>

      <!-- 配置编辑 -->
      <section class="detail-section">
        <h3>{{ t('plugins.configuration') }}</h3>
        <textarea
          v-model="configJson"
          class="config-editor"
          rows="8"
          spellcheck="false"
        />
        <div class="config-actions">
          <button @click="saveConfig" class="btn-primary">{{ t('plugins.saveConfig') }}</button>
          <button @click="resetConfig" class="btn-secondary">{{ t('plugins.reset') }}</button>
        </div>
        <div v-if="configSaved" class="config-msg ok">{{ t('plugins.configSaved') }}</div>
        <div v-if="configError" class="config-msg error">{{ configError }}</div>
      </section>

      <!-- 插件日志 -->
      <section class="detail-section">
        <h3>{{ t('plugins.logs') }}</h3>
        <pre v-if="logs" class="log-viewer">{{ logs }}</pre>
        <div v-else class="log-empty">{{ t('plugins.noLogs') }}</div>
      </section>

      <!-- 插件扩展区域（README 等） -->
      <section
        v-for="section in pluginDetailSections"
        :key="section.id"
        class="detail-section"
      >
        <h3>{{ getLocalizedLabel(section.label) }}</h3>
        <PluginHost
          :plugin-name="section.pluginName"
          :component-name="section.component"
        />
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { usePluginsStore, type PluginInfo } from '@/stores/plugins'
import PluginHost from '@/plugin-system/PluginHost.vue'

const props = defineProps<{
  pluginName: string | null
}>()

const { t, locale } = useI18n()
const pluginsStore = usePluginsStore()

const configJson = ref('')
const configSaved = ref(false)
const configError = ref<string | null>(null)
const logs = ref<string | null>(null)

const plugin = computed<PluginInfo | null>(() =>
  props.pluginName
    ? pluginsStore.plugins.find(p => p.name === props.pluginName) ?? null
    : null,
)

const pluginDetailSections = computed(() =>
  props.pluginName
    ? pluginsStore.detailSections
        .filter(s => s.pluginName === props.pluginName)
        .sort((a, b) => a.order - b.order)
    : [],
)

function getLocalizedLabel(label: Record<string, string>) {
  return label[locale.value] ?? label['en'] ?? Object.values(label)[0] ?? ''
}

// 切换插件时重新加载配置
watch(
  () => props.pluginName,
  (name) => {
    configSaved.value = false
    configError.value = null
    if (name && plugin.value) {
      configJson.value = JSON.stringify(plugin.value.config, null, 2)
      logs.value = null
    } else {
      configJson.value = ''
      logs.value = null
    }
  },
  { immediate: true },
)

async function saveConfig() {
  if (!props.pluginName) return
  configError.value = null
  try {
    const parsed = JSON.parse(configJson.value)
    await pluginsStore.updateConfig(props.pluginName, parsed)
    configSaved.value = true
    setTimeout(() => {
      configSaved.value = false
    }, 2000)
  } catch (e: any) {
    if (e instanceof SyntaxError) {
      configError.value = `Invalid JSON: ${e.message}`
    } else {
      configError.value = e.message ?? t('plugins.configSaveFailed')
    }
  }
}

function resetConfig() {
  if (plugin.value) {
    configJson.value = JSON.stringify(plugin.value.config, null, 2)
  }
}
</script>

<style scoped>
.plugin-detail {
  padding: 24px 32px;
  height: 100%;
  overflow-y: auto;
  color: var(--text-primary);
}

.detail-header {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 20px;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 12px;
}

.detail-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.detail-version {
  font-size: 12px;
  color: var(--text-tertiary);
}

.detail-empty {
  color: var(--text-tertiary);
  font-size: 13px;
  padding: 40px 0;
  text-align: center;
}

.detail-section {
  margin-bottom: 20px;
}

.detail-section h3 {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  margin: 0 0 10px;
}

.detail-row {
  display: flex;
  gap: 12px;
  font-size: 13px;
  padding: 4px 0;
}

.detail-row .label {
  color: var(--text-tertiary);
  min-width: 60px;
}

.status-on {
  color: var(--success);
}

.status-off {
  color: var(--text-tertiary);
}

.detail-error {
  margin-top: 8px;
  padding: 8px 12px;
  background: var(--danger-muted);
  color: var(--danger);
  border-radius: 6px;
  font-size: 12px;
}

.config-editor {
  width: 100%;
  background: var(--bg-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  color: var(--text-primary);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
  padding: 10px;
  resize: vertical;
  box-sizing: border-box;
}

.config-editor:focus {
  outline: none;
  border-color: var(--accent);
}

.config-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.btn-primary,
.btn-secondary {
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  border: none;
  transition: background var(--transition);
}

.btn-primary {
  background: var(--accent);
  color: #fff;
}

.btn-primary:hover {
  opacity: 0.85;
}

.btn-secondary {
  background: var(--bg-glass);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}

.btn-secondary:hover {
  background: var(--bg-glass-hover);
}

.config-msg {
  margin-top: 8px;
  font-size: 12px;
}

.config-msg.ok {
  color: var(--success);
}

.config-msg.error {
  color: var(--danger);
}

.log-viewer {
  background: var(--bg-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  color: var(--text-secondary);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 11px;
  padding: 10px;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-empty {
  color: var(--text-tertiary);
  font-size: 12px;
}
</style>
