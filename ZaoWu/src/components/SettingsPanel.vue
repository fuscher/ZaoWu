<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Palette, Bot, Plus, Pencil, Trash2, Eye, EyeOff, Check, X, Server, Users, Puzzle } from '@lucide/vue'
import { useSettingsStore } from '@/stores/settings'
import { useChatStore } from '@/stores/chat'
import { usePluginsStore } from '@/stores/plugins'
import { PluginHost } from '@/plugin-system'
import { backgroundRegistry } from './backgrounds/index'
import { saveProviders } from '@/services/ai'
import { useI18n } from '@/i18n'
import NumberInput from './NumberInput.vue'
import type { Theme, LLMProvider } from '@/types'

const props = defineProps<{ theme: Theme; highlightSection?: string | null }>()
const emit = defineEmits<{ toggleTheme: []; highlight: [section: string | null] }>()

const settingsStore = useSettingsStore()
const chatStore = useChatStore()
const pluginsStore = usePluginsStore()
const { t, locale } = useI18n()

function getLocalizedLabel(label: Record<string, string>): string {
  return label[locale.value] ?? label['en'] ?? Object.values(label)[0] ?? ''
}

watch(() => props.highlightSection, (val) => {
  if (val) {
    const element = document.getElementById(`sec-${val}`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
      element.classList.add('highlighted')
      setTimeout(() => {
        element.classList.remove('highlighted')
      }, 3000)
      emit('highlight', null)
    }
  }
})

// ── Provider editing state ────────────────────────────────
const editingProvider = ref<LLMProvider | null>(null)
const isNewProvider = ref(false)
const showApiKey = ref(false)
const newModelId = ref('')
const showDeleteConfirm = ref<string | null>(null)

function openAddProvider() {
  editingProvider.value = {
    id: '',
    name: '',
    apiBase: '',
    apiKey: '',
    models: [],
  }
  isNewProvider.value = true
  showApiKey.value = true
}

function openEditProvider(provider: LLMProvider) {
  editingProvider.value = { ...provider, models: [...provider.models] }
  isNewProvider.value = false
  showApiKey.value = false
}

function cancelEdit() {
  editingProvider.value = null
  newModelId.value = ''
}

function addModel() {
  if (!newModelId.value.trim() || !editingProvider.value) return
  const exists = editingProvider.value.models.some((m) => m.id === newModelId.value.trim())
  if (exists) return
  editingProvider.value.models.push({ id: newModelId.value.trim(), name: newModelId.value.trim() })
  newModelId.value = ''
}

function removeModel(index: number) {
  editingProvider.value?.models.splice(index, 1)
}

async function saveProvider() {
  if (!editingProvider.value) return
  const p = editingProvider.value
  if (!p.name.trim() || !p.apiBase.trim()) return

  if (isNewProvider.value) {
    p.id = `provider-${Date.now()}`
    chatStore.providers.push(p)
  } else {
    const idx = chatStore.providers.findIndex((x) => x.id === p.id)
    if (idx !== -1) chatStore.providers[idx] = p
  }

  await saveProviders(chatStore.providers)
  editingProvider.value = null
  newModelId.value = ''
}

async function deleteProvider(id: string) {
  chatStore.providers = chatStore.providers.filter((p) => p.id !== id)
  await saveProviders(chatStore.providers)
  showDeleteConfirm.value = null
}

function maskApiKey(key: string) {
  if (!key) return ''
  if (key.length <= 8) return '••••••••'
  return key.slice(0, 4) + '••••••••' + key.slice(-4)
}

onMounted(() => {
  chatStore.loadProviders()
})
</script>

<template>
  <div class="settings-panel">
    <div class="settings-scroll">

      <!-- ── Appearance Section ──────────────────────────── -->
      <section class="settings-section" id="sec-appearance">
        <div class="section-header">
          <Palette :size="16" />
          <h2 class="section-title">{{ t('settings.appearance') }}</h2>
        </div>

        <div class="setting-card">
          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.theme') }}</span>
              <span class="setting-desc">{{ theme === 'dark' ? t('settings.darkMode') : t('settings.lightMode') }}</span>
            </div>
            <label class="toggle">
              <input type="checkbox" :checked="theme === 'dark'" @change="emit('toggleTheme')" />
              <span class="toggle-slider"></span>
            </label>
          </div>

          <div class="setting-divider" />

          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.background') }}</span>
              <span class="setting-desc">{{ settingsStore.background.enabled ? 'ON' : 'OFF' }}</span>
            </div>
            <label class="toggle">
              <input type="checkbox" :checked="settingsStore.background.enabled" @change="settingsStore.updateBg({ enabled: !settingsStore.background.enabled })" />
              <span class="toggle-slider"></span>
            </label>
          </div>

          <div class="setting-divider" />

          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.effect') }}</span>
            </div>
            <select
              class="setting-select"
              :value="settingsStore.background.effect"
              @change="settingsStore.updateBg({ effect: ($event.target as HTMLSelectElement).value })"
            >
              <option v-for="bg in backgroundRegistry" :key="bg.meta.id" :value="bg.meta.id">
                {{ t('backgrounds.' + bg.meta.id) }}
              </option>
            </select>
          </div>

          <div class="setting-divider" />

          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.language') }}</span>
            </div>
            <select
              class="setting-select"
              :value="settingsStore.background.language"
              @change="settingsStore.updateBg({ language: ($event.target as HTMLSelectElement).value })"
            >
              <option value="zh-CN">中文</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>
      </section>

      <!-- ── AI Models Section ───────────────────────────── -->
      <section class="settings-section" id="sec-ai-models">
        <div class="section-header">
          <Bot :size="16" />
          <h2 class="section-title">{{ t('settings.aiModels') }}</h2>
        </div>

        <!-- Empty state -->
        <div v-if="chatStore.providers.length === 0 && !editingProvider" class="empty-state">
          <Server :size="36" class="empty-icon" />
          <p class="empty-title">{{ t('settings.noProviders') }}</p>
          <p class="empty-desc">{{ t('settings.noProvidersDesc') }}</p>
        </div>

        <!-- Provider cards -->
        <div v-for="provider in chatStore.providers" :key="provider.id" class="provider-card">
          <template v-if="editingProvider?.id !== provider.id">
            <div class="provider-header">
              <div class="provider-info">
                <span class="provider-name">{{ provider.name }}</span>
                <span class="provider-base">{{ provider.apiBase }}</span>
              </div>
              <div class="provider-actions">
                <button class="icon-btn" :title="t('settings.editProvider')" @click="openEditProvider(provider)">
                  <Pencil :size="14" />
                </button>
                <button class="icon-btn danger" :title="t('settings.delete')" @click="showDeleteConfirm = provider.id">
                  <Trash2 :size="14" />
                </button>
              </div>
            </div>
            <div class="provider-meta">
              <span class="meta-tag" :class="{ ok: provider.apiKey }">
                {{ provider.apiKey ? t('settings.apiKeyMasked') : t('settings.apiKeyNotSet') }}
              </span>
              <span class="meta-tag">{{ provider.models.length }} {{ t('settings.models') }}</span>
            </div>
            <!-- Delete confirmation -->
            <div v-if="showDeleteConfirm === provider.id" class="delete-confirm">
              <span>{{ t('settings.confirmDeleteProvider', { name: provider.name }) }}</span>
              <div class="confirm-actions">
                <button class="btn-sm danger" @click="deleteProvider(provider.id)">{{ t('settings.delete') }}</button>
                <button class="btn-sm" @click="showDeleteConfirm = null">{{ t('settings.cancel') }}</button>
              </div>
            </div>
          </template>

          <!-- Inline edit form -->
          <template v-else>
            <div class="edit-form">
              <div class="form-field">
                <label>{{ t('settings.providerName') }}</label>
                <input v-model="editingProvider.name" :placeholder="t('settings.providerNamePlaceholder')" class="form-input" />
              </div>
              <div class="form-field">
                <label>{{ t('settings.apiBase') }}</label>
                <input v-model="editingProvider.apiBase" :placeholder="t('settings.apiBasePlaceholder')" class="form-input" />
              </div>
              <div class="form-field">
                <label>{{ t('settings.apiKey') }}</label>
                <div class="apikey-row">
                  <input
                    v-model="editingProvider.apiKey"
                    :type="showApiKey ? 'text' : 'password'"
                    :placeholder="t('settings.apiKeyPlaceholder')"
                    class="form-input"
                  />
                  <button class="icon-btn" @click="showApiKey = !showApiKey">
                    <Eye v-if="showApiKey" :size="14" />
                    <EyeOff v-else :size="14" />
                  </button>
                </div>
              </div>
              <div class="form-field">
                <label>{{ t('settings.models') }}</label>
                <div class="model-list-edit">
                  <div v-for="(model, idx) in editingProvider.models" :key="model.id" class="model-chip">
                    <span>{{ model.id }}</span>
                    <button class="chip-remove" @click="removeModel(idx)">×</button>
                  </div>
                </div>
                <div class="add-model-row">
                  <input
                    v-model="newModelId"
                    :placeholder="t('settings.modelIdPlaceholder')"
                    class="form-input compact"
                    @keydown.enter="addModel"
                  />
                  <button class="btn-sm accent" @click="addModel">{{ t('settings.addModel') }}</button>
                </div>
              </div>
              <div class="form-actions">
                <button class="btn-sm accent" @click="saveProvider">
                  <Check :size="12" /> {{ t('settings.save') }}
                </button>
                <button class="btn-sm" @click="cancelEdit">
                  <X :size="12" /> {{ t('settings.cancel') }}
                </button>
              </div>
            </div>
          </template>
        </div>

        <!-- Add Provider (shown as form if editing new) -->
        <template v-if="editingProvider && isNewProvider">
          <div class="provider-card new">
            <div class="edit-form">
              <div class="form-field">
                <label>{{ t('settings.providerName') }}</label>
                <input v-model="editingProvider.name" :placeholder="t('settings.providerNamePlaceholder')" class="form-input" />
              </div>
              <div class="form-field">
                <label>{{ t('settings.apiBase') }}</label>
                <input v-model="editingProvider.apiBase" :placeholder="t('settings.apiBasePlaceholder')" class="form-input" />
              </div>
              <div class="form-field">
                <label>{{ t('settings.apiKey') }}</label>
                <div class="apikey-row">
                  <input
                    v-model="editingProvider.apiKey"
                    :type="showApiKey ? 'text' : 'password'"
                    :placeholder="t('settings.apiKeyPlaceholder')"
                    class="form-input"
                  />
                  <button class="icon-btn" @click="showApiKey = !showApiKey">
                    <Eye v-if="showApiKey" :size="14" />
                    <EyeOff v-else :size="14" />
                  </button>
                </div>
              </div>
              <div class="form-field">
                <label>{{ t('settings.models') }}</label>
                <div class="model-list-edit">
                  <div v-for="(model, idx) in editingProvider.models" :key="model.id" class="model-chip">
                    <span>{{ model.id }}</span>
                    <button class="chip-remove" @click="removeModel(idx)">×</button>
                  </div>
                </div>
                <div class="add-model-row">
                  <input
                    v-model="newModelId"
                    :placeholder="t('settings.modelIdPlaceholder')"
                    class="form-input compact"
                    @keydown.enter="addModel"
                  />
                  <button class="btn-sm accent" @click="addModel">{{ t('settings.addModel') }}</button>
                </div>
              </div>
              <div class="form-actions">
                <button class="btn-sm accent" @click="saveProvider">
                  <Check :size="12" /> {{ t('settings.save') }}
                </button>
                <button class="btn-sm" @click="cancelEdit">
                  <X :size="12" /> {{ t('settings.cancel') }}
                </button>
              </div>
            </div>
          </div>
        </template>

        <!-- Add button -->
        <button v-if="!editingProvider" class="add-provider-btn" @click="openAddProvider">
          <Plus :size="14" />
          {{ t('settings.addProvider') }}
        </button>
      </section>

      <!-- ── Community Section ───────────────────────────── -->
      <section class="settings-section" id="sec-community">
        <div class="section-header">
          <Users :size="16" />
          <h2 class="section-title">{{ t('settings.community') }}</h2>
        </div>

        <div class="setting-card">
          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.communityMaxUsers') }}</span>
              <span class="setting-desc">1–10</span>
            </div>
            <NumberInput
              :model-value="settingsStore.background.communityMaxUsers"
              @update:model-value="settingsStore.updateBg({ communityMaxUsers: $event })"
              :min="1"
              :max="10"
              :step="1"
              variant="stepper"
            />
          </div>

          <div class="setting-divider" />

          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.communityDefaultRole') }}</span>
            </div>
            <select
              class="setting-select"
              :value="settingsStore.background.communityDefaultRole"
              @change="settingsStore.updateBg({ communityDefaultRole: ($event.target as HTMLSelectElement).value })"
            >
              <option value="collaborator">{{ t('community.roleCollaborator') }}</option>
              <option value="observer">{{ t('community.roleObserver') }}</option>
            </select>
          </div>

          <div class="setting-divider" />

          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.communityFileSizeLimitKB') }}</span>
              <span class="setting-desc">512 KB recommended</span>
            </div>
            <NumberInput
              :model-value="settingsStore.background.communityFileSizeLimitKB"
              @update:model-value="settingsStore.updateBg({ communityFileSizeLimitKB: $event })"
              :min="64"
              :max="2048"
              :step="64"
              unit="KB"
              variant="input"
            />
          </div>

          <div class="setting-divider" />

          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.communityInactiveTimeoutMinutes') }}</span>
              <span class="setting-desc">Default 120 min</span>
            </div>
            <NumberInput
              :model-value="settingsStore.background.communityInactiveTimeoutMinutes"
              @update:model-value="settingsStore.updateBg({ communityInactiveTimeoutMinutes: $event })"
              :min="10"
              :max="1440"
              :step="10"
              unit="min"
              variant="input"
            />
          </div>
        </div>
      </section>

      <section class="settings-section" id="sec-plugins">
        <div class="section-header">
          <Puzzle :size="16" />
          <h2 class="section-title">{{ t('settings.plugins') }}</h2>
        </div>

        <template v-for="section in pluginsStore.settingsSections" :key="section.id">
          <div class="plugin-settings-block">
            <h3>{{ getLocalizedLabel(section.label) }}</h3>
            <PluginHost :plugin-name="section.pluginName" :component-name="section.component" />
          </div>
        </template>

        <div v-if="pluginsStore.settingsSections.length === 0" class="settings-empty">
          {{ t('settings.noSettings') }}
        </div>
      </section>

    </div>
  </div>
</template>

<style scoped>
.settings-panel {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.settings-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
}

/* ── Sections ─────────────────────────────────────────── */

.settings-section {
  margin-bottom: 32px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  color: var(--text-secondary);
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

/* ── Setting Card ─────────────────────────────────────── */

.setting-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 4px 0;
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
}

.setting-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.setting-label {
  font-size: 13px;
  color: var(--text-primary);
}

.setting-desc {
  font-size: 11px;
  color: var(--text-tertiary);
}

.setting-divider {
  height: 1px;
  background: var(--border-subtle);
  margin: 0 16px;
}

/* ── Toggle ───────────────────────────────────────────── */

.toggle {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
  flex-shrink: 0;
}

.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: var(--bg-glass);
  border-radius: 10px;
  transition: all var(--transition);
  border: 1px solid var(--border-glass);
}

.toggle-slider::before {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  left: 2px;
  bottom: 2px;
  background: var(--text-tertiary);
  border-radius: 50%;
  transition: all var(--transition);
}

.toggle input:checked + .toggle-slider {
  background: var(--accent-muted);
  border-color: var(--accent);
}

.toggle input:checked + .toggle-slider::before {
  background: var(--accent);
  transform: translateX(16px);
}

/* ── Select ───────────────────────────────────────────── */

.setting-select {
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 6px;
  padding: 5px 10px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  min-width: 120px;
}

.setting-select:focus {
  border-color: var(--accent);
}

.setting-select option {
  background: var(--bg-primary);
  color: var(--text-primary);
}

/* ── Number input ─────────────────────────────────────── */

.setting-input {
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 6px;
  padding: 5px 10px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  min-width: 80px;
  text-align: right;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
}

.setting-input:focus {
  border-color: var(--accent);
}

.setting-input.number::-webkit-inner-spin-button,
.setting-input.number::-webkit-outer-spin-button {
  opacity: 1;
}

/* ── Provider Card ────────────────────────────────────── */

.provider-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 10px;
  transition: border-color var(--transition);
}

.provider-card:hover {
  border-color: var(--border-glass);
}

.provider-card.new {
  border-color: var(--accent);
  border-style: dashed;
}

.provider-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.provider-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.provider-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.provider-base {
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.provider-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.provider-meta {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.meta-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--bg-glass);
  color: var(--text-tertiary);
}

.meta-tag.ok {
  color: var(--success);
  background: var(--success-muted);
}

/* ── Delete Confirm ───────────────────────────────────── */

.delete-confirm {
  margin-top: 12px;
  padding: 10px 12px;
  background: var(--danger-muted);
  border: 1px solid var(--danger-border);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.confirm-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

/* ── Edit Form ────────────────────────────────────────── */

.edit-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-field label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.3px;
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
}

.form-input:focus {
  border-color: var(--accent);
}

.form-input::placeholder {
  color: var(--text-tertiary);
}

.form-input.compact {
  padding: 6px 10px;
  font-size: 12px;
}

.apikey-row {
  display: flex;
  gap: 6px;
}

.apikey-row .form-input {
  flex: 1;
}

/* ── Model chips ──────────────────────────────────────── */

.model-list-edit {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}

.model-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-primary);
}

.chip-remove {
  border: none;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0 2px;
}

.chip-remove:hover {
  color: var(--danger);
}

.add-model-row {
  display: flex;
  gap: 6px;
}

.add-model-row .form-input {
  flex: 1;
}

/* ── Form Actions ─────────────────────────────────────── */

.form-actions {
  display: flex;
  gap: 8px;
  padding-top: 4px;
}

/* ── Buttons ──────────────────────────────────────────── */

.icon-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all var(--transition);
}

.icon-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

.icon-btn.danger:hover {
  background: var(--danger-muted);
  color: var(--danger);
}

.btn-sm {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  color: var(--text-secondary);
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition);
}

.btn-sm:hover {
  background: var(--bg-glass-hover);
}

.btn-sm.accent {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.btn-sm.accent:hover {
  background: var(--accent-hover);
}

.btn-sm.danger {
  background: var(--danger);
  border-color: var(--danger);
  color: #fff;
}

.btn-sm.danger:hover {
  opacity: 0.9;
}

/* ── Add Provider Button ──────────────────────────────── */

.add-provider-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 10px;
  border: 1px dashed var(--border-glass);
  background: transparent;
  color: var(--text-tertiary);
  border-radius: 12px;
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition);
}

.add-provider-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-muted);
}

/* ── Empty State ──────────────────────────────────────── */

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px;
  gap: 6px;
}

.empty-icon {
  color: var(--text-tertiary);
  opacity: 0.4;
  margin-bottom: 4px;
}

.empty-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0;
}

.empty-desc {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 0;
}

/* ── Highlight Animation ──────────────────────────────── */

.settings-section.highlighted {
  animation: highlight-pulse 1.5s ease-out;
}

@keyframes highlight-pulse {
  0% {
    box-shadow: 0 0 0 0 var(--accent-muted);
  }
  50% {
    box-shadow: 0 0 0 8px var(--accent-muted);
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}

/* ── 插件设置分区 ── */

.plugin-settings-block {
  margin-bottom: 16px;
}

.plugin-settings-block h3 {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  margin: 0 0 8px;
}

.settings-empty {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 16px 0;
  text-align: center;
}
</style>
