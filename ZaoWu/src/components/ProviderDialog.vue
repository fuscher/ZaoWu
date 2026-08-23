<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { X, Eye, EyeOff, ChevronDown, Server, Search, RefreshCw, Check, Plus, ArrowLeft, Settings2, Download, Sparkles } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { LLMProvider, LLMModel, LLMProviderPreset } from '@/types'
import { fetchProviderPresets, fetchModelsByConfig } from '@/services/ai'

const props = defineProps<{
  modelValue: boolean
  provider: LLMProvider | null
  isNew: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [provider: LLMProvider]
}>()
const { t } = useI18n()

// ── 视图状态 ─────────────────────────────────────────────
/** setup=配置表单；import=模型勾选导入（弹窗内二级视图，避免弹窗套弹窗） */
const view = ref<'setup' | 'import'>('setup')
/** 新建时：preset=预设选择；form=配置表单（已选预设或自定义） */
const phase = ref<'preset' | 'form'>('form')
const showAdvanced = ref(true)
const showApiKey = ref(false)
const saving = ref(false)
const fetching = ref(false)
const fetchError = ref('')
const toast = ref('')

// ── 表单草稿 ─────────────────────────────────────────────
const draft = ref<LLMProvider>({
  id: '',
  name: '',
  apiBase: '',
  apiKey: '',
  models: [],
  presetId: 'custom',
  protocol: 'openai',
  authType: 'bearer',
  chatPath: '',
})

const presets = ref<LLMProviderPreset[]>([])
const selectedPresetId = ref<string | null>(null)
const presetLoaded = ref(false)

// ── 模型导入 ─────────────────────────────────────────────
const fetchedModels = ref<LLMModel[]>([])
const selectedIds = ref<Set<string>>(new Set())
const searchQuery = ref('')
const newModelName = ref('')
const newModelId = ref('')

const title = computed(() =>
  props.isNew ? t('settings.newProvider') : t('settings.editProviderTitle')
)

const isAnthropic = computed(() => draft.value.protocol === 'anthropic')

const filteredFetched = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return fetchedModels.value
  return fetchedModels.value.filter(
    (m) => m.id.toLowerCase().includes(q) || (m.name || '').toLowerCase().includes(q)
  )
})

const selectedCount = computed(() => selectedIds.value.size)

function reset() {
  view.value = 'setup'
  phase.value = 'form'
  // 高级设置默认展开（自定义/编辑场景下用户通常要改端点与鉴权）；选预设时再折叠
  showAdvanced.value = true
  showApiKey.value = false
  fetching.value = false
  fetchError.value = ''
  toast.value = ''
  fetchedModels.value = []
  selectedIds.value = new Set()
  searchQuery.value = ''
  newModelName.value = ''
  newModelId.value = ''
  selectedPresetId.value = null
}

function open() {
  reset()
  if (props.isNew) {
    draft.value = {
      id: '',
      name: '',
      apiBase: '',
      apiKey: '',
      models: [],
      presetId: 'custom',
      protocol: 'openai',
      authType: 'bearer',
      chatPath: '',
    }
    phase.value = 'preset'
    showApiKey.value = true
  } else if (props.provider) {
    draft.value = {
      ...props.provider,
      models: [...props.provider.models],
    }
    showApiKey.value = false
  }
}

watch(
  () => props.modelValue,
  (v) => {
    if (v) open()
  }
)

onMounted(async () => {
  if (!presetLoaded.value) {
    try {
      presets.value = await fetchProviderPresets()
    } catch {
      // 后端不可用时保留空预设（自定义入口仍可用）
    }
    presetLoaded.value = true
  }
})

function close() {
  if (saving.value || fetching.value) return
  emit('update:modelValue', false)
}

// ── 预设选择 ─────────────────────────────────────────────
function applyPreset(preset: LLMProviderPreset) {
  draft.value = {
    id: '',
    name: preset.name,
    apiBase: preset.apiBase,
    apiKey: '',
    models: [],
    presetId: preset.id,
    protocol: preset.protocol || 'openai',
    authType: preset.authType || 'bearer',
    chatPath: preset.chatPath || '',
  }
  selectedPresetId.value = preset.id
  phase.value = 'form'
  // 预设已内置正确端点/协议/鉴权，折叠高级设置，聚焦 API Key 输入
  showAdvanced.value = false
  showApiKey.value = true
}

function startCustom() {
  draft.value.presetId = 'custom'
  selectedPresetId.value = null
  phase.value = 'form'
  showApiKey.value = false
}

function backToPreset() {
  if (!props.isNew) return
  phase.value = 'preset'
  view.value = 'setup'
}

// ── 模型管理 ─────────────────────────────────────────────
function addManualModel() {
  const rid = newModelId.value.trim()
  if (!rid) return
  if (draft.value.models.some((m) => m.id === rid)) return
  draft.value.models.push({
    id: rid,
    name: newModelName.value.trim() || rid,
  })
  newModelId.value = ''
  newModelName.value = ''
}

function removeModel(index: number) {
  draft.value.models.splice(index, 1)
}

function canFetch(): boolean {
  if (!draft.value.apiBase.trim()) return false
  if (draft.value.authType !== 'none' && !draft.value.apiKey.trim()) return false
  return true
}

async function fetchRemoteModels() {
  if (!canFetch()) {
    fetchError.value = t('settings.fetchModelsNeedKey')
    return
  }
  fetching.value = true
  fetchError.value = ''
  try {
    const models = await fetchModelsByConfig({
      apiBase: draft.value.apiBase.trim(),
      apiKey: draft.value.apiKey.trim(),
      protocol: draft.value.protocol || 'openai',
      authType: draft.value.authType || 'bearer',
    })
    fetchedModels.value = models
    // 已导入模型默认选中但不可重复导入（合并时按 id 去重）
    const existingIds = new Set(draft.value.models.map((m) => m.id))
    selectedIds.value = new Set(existingIds)
    view.value = 'import'
  } catch (err) {
    fetchError.value = err instanceof Error ? err.message : t('settings.fetchModelsFailed')
  } finally {
    fetching.value = false
  }
}

function toggleSelect(id: string) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

function toggleSelectAll() {
  const unselected = filteredFetched.value.filter((m) => !selectedIds.value.has(m.id))
  const next = new Set(selectedIds.value)
  if (unselected.length > 0) {
    unselected.forEach((m) => next.add(m.id))
  } else {
    filteredFetched.value.forEach((m) => next.delete(m.id))
  }
  selectedIds.value = next
}

function importSelected() {
  let imported = 0
  for (const m of fetchedModels.value) {
    if (!selectedIds.value.has(m.id)) continue
    const existing = draft.value.models.find((x) => x.id === m.id)
    if (existing) {
      // 保留用户已编辑的显示名称，仅补充上下文信息
      existing.contextLength = m.contextLength ?? existing.contextLength
      continue
    }
    draft.value.models.push({
      id: m.id,
      name: m.name || m.id,
      contextLength: m.contextLength,
    })
    imported++
  }
  view.value = 'setup'
  toast.value = t('settings.importedModels', { n: imported })
  setTimeout(() => (toast.value = ''), 2500)
}

// ── 保存 ─────────────────────────────────────────────────
function validate(): string {
  if (!draft.value.name.trim()) return t('settings.providerNameRequired')
  if (!draft.value.apiBase.trim()) return t('settings.apiBaseRequired')
  if (!/^https?:\/\//i.test(draft.value.apiBase.trim())) return t('settings.apiBaseInvalid')
  return ''
}

async function save() {
  const err = validate()
  if (err) {
    fetchError.value = err
    return
  }
  saving.value = true
  try {
    if (props.isNew) {
      draft.value.id = draft.value.presetId && draft.value.presetId !== 'custom'
        ? `${draft.value.presetId}-${Date.now()}`
        : `provider-${Date.now()}`
    }
    emit('saved', { ...draft.value })
  } finally {
    saving.value = false
  }
}

function presetName(presetId: string | undefined): string {
  if (!presetId || presetId === 'custom') return ''
  return presets.value.find((p) => p.id === presetId)?.name || ''
}
</script>

<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div v-if="modelValue" class="dlg-overlay" @click.self="close">
        <div class="dlg-box">
          <!-- Header -->
          <div class="dlg-header">
            <div class="dlg-title-row">
              <Server :size="16" class="dlg-title-icon" />
              <span class="dlg-title">{{ title }}</span>
              <span v-if="isNew && phase === 'form' && draft.presetId && draft.presetId !== 'custom'" class="preset-tag">
                {{ presetName(draft.presetId) }}
              </span>
            </div>
            <button class="dlg-close" title="关闭" @click="close">
              <X :size="16" />
            </button>
          </div>

          <!-- Step 1: 预设选择（仅新建） -->
          <div v-if="isNew && phase === 'preset'" class="preset-step">
            <p class="step-hint">{{ t('settings.presetSelectDesc') }}</p>
            <div class="preset-grid">
              <button
                v-for="preset in presets"
                :key="preset.id"
                class="preset-card"
                @click="applyPreset(preset)"
              >
                <span class="preset-name">{{ preset.name }}</span>
                <span class="preset-base">{{ preset.apiBase }}</span>
              </button>
              <!-- 自定义配置与预设语义不同级：置底并独占整行，弱化卡片感 -->
              <button class="preset-card custom" @click="startCustom">
                <span class="preset-name">{{ t('settings.customProvider') }}</span>
                <span class="preset-base">{{ t('settings.customProviderDesc') }}</span>
              </button>
            </div>
          </div>

          <!-- Step 2: 配置表单 -->
          <div v-else-if="view === 'setup'" class="form-step">
            <div v-if="isNew && phase === 'form'" class="back-row">
              <button class="back-btn" @click="backToPreset">
                <ArrowLeft :size="13" /> {{ t('settings.backToPreset') }}
              </button>
            </div>

            <div class="form-field">
              <label>{{ t('settings.providerName') }}</label>
              <input
                v-model="draft.name"
                :placeholder="t('settings.providerNamePlaceholder')"
                class="form-input"
              />
            </div>

            <div class="form-field">
              <label>{{ t('settings.apiKey') }}</label>
              <div class="apikey-row">
                <input
                  v-model="draft.apiKey"
                  :type="showApiKey ? 'text' : 'password'"
                  :placeholder="draft.authType === 'none' ? t('settings.apiKeyNoneHint') : t('settings.apiKeyPlaceholder')"
                  class="form-input"
                  autocomplete="off"
                />
                <button class="icon-btn" :title="t('settings.toggleKey')" @click="showApiKey = !showApiKey">
                  <Eye v-if="showApiKey" :size="14" />
                  <EyeOff v-else :size="14" />
                </button>
              </div>
            </div>

            <!-- 高级设置（折叠） -->
            <button class="advanced-toggle" @click="showAdvanced = !showAdvanced">
              <Settings2 :size="13" />
              <span>{{ t('settings.advancedSettings') }}</span>
              <ChevronDown :size="13" class="chevron" :class="{ open: showAdvanced }" />
            </button>
            <Transition name="fold">
              <div v-if="showAdvanced" class="advanced-body">
                <div class="form-field">
                  <label>{{ t('settings.apiBase') }}</label>
                  <input
                    v-model="draft.apiBase"
                    :placeholder="t('settings.apiBasePlaceholder')"
                    class="form-input"
                  />
                </div>
                <div class="form-row">
                  <div class="form-field">
                    <label>{{ t('settings.protocol') }}</label>
                    <div class="select-wrap">
                      <select v-model="draft.protocol" class="form-select">
                        <option value="openai">{{ t('settings.protocolOpenai') }}</option>
                        <option value="anthropic">{{ t('settings.protocolAnthropic') }}</option>
                      </select>
                      <ChevronDown :size="13" class="select-arrow" />
                    </div>
                  </div>
                  <div class="form-field">
                    <label>{{ t('settings.authType') }}</label>
                    <div class="select-wrap">
                      <select v-model="draft.authType" class="form-select">
                        <option value="bearer">{{ t('settings.authBearer') }}</option>
                        <option value="x-api-key">{{ t('settings.authXApiKey') }}</option>
                        <option value="none">{{ t('settings.authNone') }}</option>
                      </select>
                      <ChevronDown :size="13" class="select-arrow" />
                    </div>
                  </div>
                </div>
                <div class="form-field">
                  <label>{{ t('settings.chatPath') }}</label>
                  <input
                    v-model="draft.chatPath"
                    :placeholder="isAnthropic ? '/v1/messages' : '/chat/completions'"
                    class="form-input"
                  />
                </div>
              </div>
            </Transition>

            <div v-if="isAnthropic" class="hint-box warn">
              <Sparkles :size="13" />
              <span>{{ t('settings.anthropicHint') }}</span>
            </div>
            <div v-if="fetchError" class="hint-box error">
              <span>{{ fetchError }}</span>
            </div>

            <!-- 模型管理 -->
            <div class="models-block">
              <div class="models-header">
                <span class="models-title">{{ t('settings.models') }} ({{ draft.models.length }})</span>
                <button
                  class="btn-sm accent"
                  :disabled="fetching"
                  :title="t('settings.fetchModelsTitle')"
                  @click="fetchRemoteModels"
                >
                  <RefreshCw v-if="!fetching" :size="13" />
                  <span v-else class="import-spinner" />
                  {{ fetching ? t('settings.fetchingModels') : t('settings.fetchModels') }}
                </button>
              </div>

              <!-- 已选模型（双字段） -->
              <div v-if="draft.models.length > 0" class="model-editor-list">
                <div v-for="(model, idx) in draft.models" :key="model.id" class="model-editor-row">
                  <input
                    v-model="model.name"
                    :placeholder="t('settings.modelDisplayNamePlaceholder')"
                    class="form-input compact flex-1"
                  />
                  <input
                    v-model="model.id"
                    :placeholder="t('settings.modelRequestIdPlaceholder')"
                    class="form-input compact flex-1 mono"
                  />
                  <button class="icon-btn danger" :title="t('settings.delete')" @click="removeModel(idx)">
                    <X :size="13" />
                  </button>
                </div>
              </div>
              <p v-else class="models-empty">{{ t('settings.noModelsYet') }}</p>

              <!-- 手动添加 -->
              <div class="add-model-row">
                <input
                  v-model="newModelName"
                  :placeholder="t('settings.modelDisplayNamePlaceholder')"
                  class="form-input compact flex-1"
                  @keydown.enter="addManualModel"
                />
                <input
                  v-model="newModelId"
                  :placeholder="t('settings.modelRequestIdPlaceholder')"
                  class="form-input compact flex-1 mono"
                  @keydown.enter="addManualModel"
                />
                <button class="btn-sm" :disabled="!newModelId.trim()" @click="addManualModel">
                  <Plus :size="13" /> {{ t('settings.addModel') }}
                </button>
              </div>
            </div>

            <div v-if="toast" class="toast-line">{{ toast }}</div>
          </div>

          <!-- Step 3: 模型导入（弹窗内二级视图） -->
          <div v-else-if="view === 'import'" class="import-step">
            <div class="back-row">
              <button class="back-btn" @click="view = 'setup'">
                <ArrowLeft :size="13" /> {{ t('settings.backToConfig') }}
              </button>
            </div>
            <div class="import-toolbar">
              <div class="search-box">
                <Search :size="13" class="search-icon" />
                <input
                  v-model="searchQuery"
                  :placeholder="t('settings.importModelsSearch')"
                  class="form-input compact"
                />
              </div>
              <button class="btn-sm" @click="toggleSelectAll">
                {{ t('settings.selectAll') }}
              </button>
            </div>

            <div v-if="filteredFetched.length === 0" class="import-empty">
              {{ t('settings.noModelsFetched') }}
            </div>
            <div v-else class="import-list">
              <div
                v-for="m in filteredFetched"
                :key="m.id"
                class="import-row"
                :class="{ selected: selectedIds.has(m.id) }"
                @click="toggleSelect(m.id)"
              >
                <span class="import-check" :class="{ on: selectedIds.has(m.id) }">
                  <Check v-if="selectedIds.has(m.id)" :size="11" />
                </span>
                <span class="import-id mono">{{ m.id }}</span>
                <span v-if="m.name && m.name !== m.id" class="import-name">{{ m.name }}</span>
                <span v-if="m.contextLength" class="import-ctx">{{ Math.round(m.contextLength / 1000) }}k</span>
                <span v-if="draft.models.some((x) => x.id === m.id)" class="import-done">
                  {{ t('settings.imported') }}
                </span>
              </div>
            </div>

            <div class="import-footer">
              <button class="btn-sm" @click="view = 'setup'">{{ t('settings.cancel') }}</button>
              <button class="btn-sm accent" :disabled="selectedCount === 0" @click="importSelected">
                <Download :size="13" />
                {{ t('settings.importSelected', { n: selectedCount }) }}
              </button>
            </div>
          </div>

          <!-- Footer（配置视图） -->
          <div v-if="view === 'setup'" class="dlg-footer">
            <button class="btn-sm" @click="close">{{ t('settings.cancel') }}</button>
            <button class="btn-sm accent" :disabled="saving" @click="save">
              <Check :size="13" /> {{ t('settings.save') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dlg-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.dlg-box {
  background: var(--bg-secondary);
  border: 1px solid var(--border-glass);
  border-radius: 14px;
  box-shadow: var(--shadow);
  width: min(560px, calc(100vw - 48px));
  max-height: min(80vh, 720px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Header ─────────────────────────────────────────── */

.dlg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.dlg-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.dlg-title-icon {
  color: var(--accent);
}

.dlg-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.preset-tag {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--accent-muted);
  color: var(--accent);
  white-space: nowrap;
}

.dlg-close {
  width: 28px;
  height: 28px;
  border: none;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.dlg-close:hover {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

/* ── Steps ──────────────────────────────────────────── */

.preset-step,
.form-step,
.import-step {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.step-hint {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0 0 12px;
}

.back-row {
  margin-bottom: 10px;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: none;
  color: var(--text-tertiary);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
}

.back-btn:hover {
  color: var(--accent);
  background: var(--bg-glass);
}

/* ── Preset grid ────────────────────────────────────── */

.preset-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.preset-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 10px;
  cursor: pointer;
  text-align: left;
  transition: all var(--transition);
}

.preset-card:hover {
  border-color: var(--accent);
  background: var(--accent-muted);
}

/* 自定义配置：与预设语义不同级 → 置底独占整行，内容横排 */
.preset-card.custom {
  grid-column: 1 / -1;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-style: dashed;
  padding: 14px 16px;
}

.preset-card.custom .preset-name {
  font-weight: 600;
}

.preset-card.custom .preset-base {
  text-align: right;
  white-space: normal;
  word-break: break-all;
}

.preset-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.preset-base {
  font-size: 10px;
  color: var(--text-tertiary);
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  word-break: break-all;
}

/* ── Form ───────────────────────────────────────────── */

.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
}

.form-field label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.form-row {
  display: flex;
  gap: 10px;
}

.form-row .form-field {
  flex: 1;
}

.form-input {
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 8px 10px;
  color: var(--text-primary);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color var(--transition);
  width: 100%;
  box-sizing: border-box;
}

.form-input:focus {
  border-color: var(--accent);
}

.form-input::placeholder {
  color: var(--text-tertiary);
}

.form-input.compact {
  padding: 6px 9px;
  font-size: 12px;
}

.form-input.mono {
  font-family: 'Cascadia Code', 'Fira Code', monospace;
}

/* ── 下拉选择（协议 / 鉴权方式）────────────────────────── */

.select-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.form-select {
  appearance: none;
  -webkit-appearance: none;
  width: 100%;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 8px 28px 8px 10px;
  color: var(--text-primary);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  cursor: pointer;
  transition: border-color var(--transition);
}

.form-select:hover {
  border-color: var(--border-hover);
}

.form-select:focus {
  border-color: var(--accent);
}

/* 下拉面板选项跟随主题（原生渲染的 option 区域） */
.form-select option {
  background: var(--bg-primary);
  color: var(--text-primary);
}

.select-arrow {
  position: absolute;
  right: 9px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
  pointer-events: none;
  flex-shrink: 0;
}

.flex-1 {
  flex: 1;
}

.apikey-row {
  display: flex;
  gap: 6px;
}

.icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: var(--bg-glass);
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all var(--transition);
  flex-shrink: 0;
}

.icon-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

.icon-btn.danger:hover {
  background: var(--danger-muted);
  color: var(--danger);
}

/* ── Advanced ────────────────────────────────────────── */

.advanced-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 0;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  border-top: 1px solid var(--border-subtle);
  margin-top: 4px;
}

.advanced-toggle:hover {
  color: var(--accent);
}

.advanced-toggle .chevron {
  margin-left: auto;
  transition: transform var(--transition);
}

.advanced-toggle .chevron.open {
  transform: rotate(180deg);
}

.advanced-body {
  padding: 8px 0 4px;
}

.fold-enter-active,
.fold-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.fold-enter-from,
.fold-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ── Hint ───────────────────────────────────────────── */

.hint-box {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 11px;
  line-height: 1.5;
  padding: 8px 10px;
  border-radius: 8px;
  margin: 6px 0;
}

.hint-box.warn {
  background: var(--danger-muted);
  border: 1px solid var(--danger-border);
  color: var(--text-secondary);
}

.hint-box.error {
  background: var(--danger-muted);
  border: 1px solid var(--danger-border);
  color: var(--danger);
}

/* ── Models ─────────────────────────────────────────── */

.models-block {
  margin-top: 12px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 10px;
}

.models-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.models-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.model-editor-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}

.model-editor-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.models-empty {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 4px 0 8px;
}

.add-model-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.toast-line {
  font-size: 12px;
  color: var(--success);
  margin-top: 8px;
}

/* ── Import view ────────────────────────────────────── */

.import-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}

.search-box {
  position: relative;
  flex: 1;
}

.search-icon {
  position: absolute;
  left: 9px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
}

.search-box .form-input {
  padding-left: 28px;
}

.import-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 6px;
}

.import-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background var(--transition);
}

.import-row:hover {
  background: var(--bg-glass);
}

.import-row.selected {
  background: var(--accent-muted);
}

.import-check {
  width: 16px;
  height: 16px;
  border: 1px solid var(--border-glass);
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--bg-glass);
}

.import-check.on {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.import-id {
  font-size: 12px;
  color: var(--text-primary);
  flex-shrink: 0;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.import-name {
  font-size: 11px;
  color: var(--text-tertiary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.import-ctx {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 1px 5px;
  border-radius: 3px;
}

.import-done {
  font-size: 10px;
  color: var(--success);
  flex-shrink: 0;
}

.import-empty {
  font-size: 12px;
  color: var(--text-tertiary);
  text-align: center;
  padding: 24px 0;
}

.import-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}

/* ── Footer ─────────────────────────────────────────── */

.dlg-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border-subtle);
}

/* ── Buttons ────────────────────────────────────────── */

.btn-sm {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  color: var(--text-secondary);
  border-radius: 8px;
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition);
}

.btn-sm:hover:not(:disabled) {
  background: var(--bg-glass-hover);
}

.btn-sm:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-sm.accent {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.btn-sm.accent:hover:not(:disabled) {
  background: var(--accent-hover);
}

.import-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--border-glass);
  border-top-color: var(--text-secondary);
  border-radius: 50%;
  animation: dlg-spin 0.8s linear infinite;
}

@keyframes dlg-spin {
  to {
    transform: rotate(360deg);
  }
}

/* ── Transition ─────────────────────────────────────── */

.dialog-enter-active,
.dialog-leave-active {
  transition: opacity 0.2s ease;
}

.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}
</style>
