<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Palette, Bot, Plus, Pencil, Trash2, Server, Users, Puzzle, Sparkles, Download, RefreshCw } from '@lucide/vue'
import { useSettingsStore } from '@/stores/settings'
import { useChatStore } from '@/stores/chat'
import { usePluginsStore } from '@/stores/plugins'
import { PluginHost } from '@/plugin-system'
import { backgroundRegistry } from './backgrounds/index'
import { saveProviders } from '@/services/ai'
import { useI18n } from '@/i18n'
import { useUpdate } from '@/composables/useUpdate'
import NumberInput from './NumberInput.vue'
import ErrorToast from './ErrorToast.vue'
import ProviderDialog from './ProviderDialog.vue'
import type { Theme, LLMProvider, ViewType } from '@/types'

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

// ── Provider dialog state ─────────────────────────────────
const providerDialogOpen = ref(false)
const dialogProvider = ref<LLMProvider | null>(null)
const dialogIsNew = ref(false)
const showDeleteConfirm = ref<string | null>(null)
const skillFileInput = ref<HTMLInputElement | null>(null)
const isImportingSkill = ref(false)
const toastMessage = ref('')
const toastType = ref<'error' | 'warning' | 'info'>('info')

function showToast(message: string, type: 'error' | 'warning' | 'info' = 'info') {
  toastMessage.value = ''
  // Force re-render so the Transition fires even for repeated messages
  requestAnimationFrame(() => {
    toastMessage.value = message
    toastType.value = type
  })
}

// ── Update state (检查更新，全局共享 composable) ─────────────
const {
  updateState, currentVersion, latestVersion, updateNotes, updateProgress,
  bindToast, checkForUpdates, startDownload, applyUpdate,
} = useUpdate()

function openAddProvider() {
  dialogProvider.value = null
  dialogIsNew.value = true
  providerDialogOpen.value = true
}

function openEditProvider(provider: LLMProvider) {
  dialogProvider.value = provider
  dialogIsNew.value = false
  providerDialogOpen.value = true
}

async function handleProviderSaved(saved: LLMProvider) {
  if (dialogIsNew.value) {
    chatStore.providers.push(saved)
  } else {
    const idx = chatStore.providers.findIndex((x) => x.id === saved.id)
    if (idx !== -1) chatStore.providers[idx] = saved
  }
  await saveProviders(chatStore.providers)
  providerDialogOpen.value = false
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

/** 协议徽标文案：anthropic=Anthropic Messages；其余=OpenAI 兼容 */
function protocolLabel(provider: LLMProvider): string {
  return provider.protocol === 'anthropic'
    ? t('settings.protocolAnthropic')
    : t('settings.protocolOpenai')
}

const IMPORT_MAX_BYTES = 512 * 1024

function openImportSkill() {
  skillFileInput.value?.click()
}

async function handleSkillFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  if (!file.name.toLowerCase().endsWith('.md')) {
    showToast(t('settings.importSkillInvalidExtension'), 'error')
    input.value = ''
    return
  }

  if (file.size > IMPORT_MAX_BYTES) {
    showToast(t('settings.importSkillTooLarge'), 'error')
    input.value = ''
    return
  }

  isImportingSkill.value = true
  try {
    const content = await file.text()
    const skill = await chatStore.importSkill(content)
    if (!skill) {
      showToast(t('settings.importSkillFailed'), 'error')
    } else {
      showToast(t('settings.importSkillSuccess', { name: skill.description || skill.name }), 'info')
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : t('settings.importSkillFailed')
    showToast(message, 'error')
  } finally {
    isImportingSkill.value = false
    input.value = ''
  }
}

async function toggleSkill(name: string, enabled: boolean) {
  try {
    if (enabled) {
      await chatStore.disableSkill(name)
    } else {
      await chatStore.enableSkill(name)
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : t('settings.skillActionFailed')
    showToast(message, 'error')
  }
}

async function removeSkill(name: string) {
  try {
    await chatStore.deleteSkill(name)
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : t('settings.skillActionFailed')
    showToast(message, 'error')
  }
}

onMounted(() => {
  chatStore.loadProviders()
  chatStore.loadSkills()
  bindToast(showToast)
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

          <div class="setting-divider" />

          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.startupView') }}</span>
              <span class="setting-desc">{{ t('settings.startupViewDesc') }}</span>
            </div>
            <select
              class="setting-select"
              :value="settingsStore.background.startupView"
              @change="settingsStore.updateBg({ startupView: ($event.target as HTMLSelectElement).value as ViewType })"
            >
              <option value="chat">{{ t('activityBar.chat') }}</option>
              <option value="workflow">{{ t('activityBar.workflow') }}</option>
              <option value="files">{{ t('activityBar.files') }}</option>
              <option value="search">{{ t('activityBar.search') }}</option>
              <option value="git">{{ t('activityBar.git') }}</option>
              <option value="plugins">{{ t('activityBar.plugins') }}</option>
              <option value="community">{{ t('activityBar.community') }}</option>
              <option value="settings">{{ t('activityBar.settings') }}</option>
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
        <div v-if="chatStore.providers.length === 0" class="empty-state">
          <Server :size="36" class="empty-icon" />
          <p class="empty-title">{{ t('settings.noProviders') }}</p>
          <p class="empty-desc">{{ t('settings.noProvidersDesc') }}</p>
        </div>

        <!-- Provider cards -->
        <div v-for="provider in chatStore.providers" :key="provider.id" class="provider-card">
          <div class="provider-header">
            <div class="provider-info">
              <div class="provider-name-row">
                <span class="provider-name">{{ provider.name }}</span>
                <span class="protocol-tag">{{ protocolLabel(provider) }}</span>
              </div>
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
            <span v-if="provider.authType === 'none'" class="meta-tag">{{ t('settings.authNone') }}</span>
          </div>
          <!-- Delete confirmation -->
          <div v-if="showDeleteConfirm === provider.id" class="delete-confirm">
            <span>{{ t('settings.confirmDeleteProvider', { name: provider.name }) }}</span>
            <div class="confirm-actions">
              <button class="btn-sm danger" @click="deleteProvider(provider.id)">{{ t('settings.delete') }}</button>
              <button class="btn-sm" @click="showDeleteConfirm = null">{{ t('settings.cancel') }}</button>
            </div>
          </div>
        </div>

        <!-- Add button -->
        <button class="add-provider-btn" @click="openAddProvider">
          <Plus :size="14" />
          {{ t('settings.addProvider') }}
        </button>

        <!-- Provider edit/create dialog -->
        <ProviderDialog
          v-model="providerDialogOpen"
          :provider="dialogProvider"
          :is-new="dialogIsNew"
          @saved="handleProviderSaved"
        />
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

      <section class="settings-section" id="sec-skills">
        <div class="section-header">
          <Sparkles :size="16" />
          <h2 class="section-title">{{ t('settings.skills') }}</h2>
          <button
            class="btn-sm import-skill-btn"
            :title="t('settings.importSkill')"
            :disabled="isImportingSkill"
            @click="openImportSkill"
          >
            <Download v-if="!isImportingSkill" :size="14" />
            <span v-else class="import-spinner" />
            <span>{{ isImportingSkill ? t('settings.importingSkill') : t('settings.importSkill') }}</span>
          </button>
          <input
            ref="skillFileInput"
            type="file"
            accept=".md"
            style="display: none"
            @change="handleSkillFileSelected"
          />
        </div>

        <div class="settings-desc">
          {{ t('settings.importSkillDesc') }}
        </div>

        <div v-if="chatStore.availableSkills.length === 0" class="settings-empty">
          {{ t('settings.noSkills') }}
        </div>

        <div v-else class="skill-list">
          <div
            v-for="skill in chatStore.availableSkills"
            :key="skill.name"
            class="skill-item"
          >
            <div class="skill-info">
              <span class="skill-name">{{ skill.name }}</span>
              <span v-if="skill.description && skill.description !== skill.name" class="skill-desc">
                {{ skill.description }}
              </span>
              <span class="skill-source">
                {{ skill.source === 'builtin' ? t('settings.builtin') : t('settings.pluginProvided') }}
              </span>
            </div>
            <div class="skill-actions">
              <label
                class="toggle skill-toggle"
                :title="skill.enabled ? t('settings.disable') : t('settings.enable')"
              >
                <input
                  type="checkbox"
                  :checked="skill.enabled"
                  @change="toggleSkill(skill.name, skill.enabled)"
                />
                <span class="toggle-slider" />
              </label>
              <span class="skill-status">
                {{ skill.enabled ? t('settings.enabled') : t('settings.disabled') }}
              </span>
              <button
                v-if="skill.source === 'builtin'"
                class="icon-btn danger"
                :title="t('settings.delete')"
                @click="removeSkill(skill.name)"
              >
                <Trash2 :size="14" />
              </button>
              <span v-else class="skill-plugin-hint">{{ t('settings.pluginProvided') }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- ── Update Section ──────────────────────────────── -->
      <section class="settings-section" id="sec-update">
        <div class="section-header">
          <RefreshCw :size="16" />
          <h2 class="section-title">{{ t('settings.update') }}</h2>
        </div>

        <div class="setting-card">
          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.currentVersion') }}</span>
              <span class="setting-desc">{{ currentVersion || '—' }}</span>
            </div>
            <span v-if="updateState === 'unsupported'" class="update-hint">
              {{ t('settings.devModeUnsupported') }}
            </span>
            <button
              v-else
              class="btn-sm accent"
              :disabled="updateState === 'checking' || updateState === 'downloading' || updateState === 'applying'"
              @click="checkForUpdates"
            >
              <span v-if="updateState === 'checking'" class="import-spinner" />
              {{ updateState === 'checking' ? t('settings.checkingUpdate') : t('settings.checkForUpdates') }}
            </button>
          </div>

          <div class="setting-divider" />

          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{{ t('settings.autoCheckUpdates') }}</span>
              <span class="setting-desc">{{ t('settings.autoCheckUpdatesDesc') }}</span>
            </div>
            <button
              class="toggle-btn"
              :class="{ active: settingsStore.background.autoCheckUpdates }"
              @click="settingsStore.updateBg({ autoCheckUpdates: !settingsStore.background.autoCheckUpdates })"
            >
              <span class="toggle-knob" />
            </button>
          </div>

          <template v-if="['available', 'downloading', 'ready', 'applying'].includes(updateState)">
            <div class="setting-divider" />

            <div class="setting-row">
              <div class="setting-info">
                <span class="setting-label">{{ t('settings.latestVersion') }}</span>
                <span class="setting-desc">{{ latestVersion }}</span>
                <span v-if="updateNotes" class="update-notes">{{ updateNotes }}</span>
              </div>
            </div>

            <div class="setting-divider" />

            <div class="setting-row">
              <div class="setting-info">
                <span class="setting-label">{{ t('settings.downloadingUpdate') }}</span>
                <span class="setting-desc">{{ updateProgress }}%</span>
              </div>
              <span v-if="updateState === 'applying'" class="update-hint">
                {{ t('settings.restarting') }}
              </span>
              <button
                v-else-if="updateState === 'ready'"
                class="btn-sm accent"
                @click="applyUpdate"
              >
                {{ t('settings.restartNow') }}
              </button>
              <button
                v-else-if="updateState === 'available'"
                class="btn-sm accent"
                @click="startDownload"
              >
                <Download :size="14" />
                {{ t('settings.downloadUpdate') }}
              </button>
            </div>

            <div class="update-progress">
              <div class="update-progress-fill" :style="{ width: updateProgress + '%' }" />
            </div>
          </template>
        </div>
      </section>

    </div>

    <Teleport to="body">
      <ErrorToast
        v-if="toastMessage"
        :message="toastMessage"
        :type="toastType"
        @close="toastMessage = ''"
      />
    </Teleport>
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
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.settings-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 12px;
  line-height: 1.5;
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

.provider-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.protocol-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--accent-muted);
  color: var(--accent);
  white-space: nowrap;
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

/* ── 技能管理 ── */

.skill-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skill-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  transition: border-color var(--transition);
}

.skill-item:hover {
  border-color: var(--accent-muted);
}

.skill-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.skill-name {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.skill-desc {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.skill-source {
  font-size: 11px;
  color: var(--text-tertiary);
}

.skill-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.skill-toggle {
  width: 28px;
  height: 16px;
}

.skill-toggle .toggle-slider::before {
  width: 12px;
  height: 12px;
}

.skill-toggle input:checked + .toggle-slider::before {
  transform: translateX(12px);
}

.skill-status {
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 48px;
}

.skill-plugin-hint {
  font-size: 11px;
  color: var(--text-tertiary);
}

.import-skill-btn {
  flex-shrink: 0;
}

.import-skill-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.import-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border-glass);
  border-top-color: var(--text-secondary);
  border-radius: 50%;
  animation: import-spin 0.8s linear infinite;
}

@keyframes import-spin {
  to {
    transform: rotate(360deg);
  }
}

/* ── 检查更新区块 ────────────────────────────────────────── */

.update-progress {
  height: 6px;
  margin: 4px 0 2px;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 3px;
  overflow: hidden;
}

.update-progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.4s ease;
}

.update-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  white-space: normal;
  max-width: 60%;
  text-align: right;
}

.update-notes {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.toggle-btn {
  width: 36px;
  height: 20px;
  border-radius: 10px;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  cursor: pointer;
  position: relative;
  flex-shrink: 0;
  transition: background 0.2s, border-color 0.2s;
}

.toggle-btn.active {
  background: var(--accent);
  border-color: var(--accent);
}

.toggle-knob {
  display: block;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--text-secondary);
  position: absolute;
  top: 2px;
  left: 2px;
  transition: transform 0.2s, background 0.2s;
}

.toggle-btn.active .toggle-knob {
  transform: translateX(16px);
  background: #fff;
}
</style>
