<script setup lang="ts">
import { ref } from 'vue'
import { X } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useCommunityStore } from '@/stores/community'
import { useProjectsStore } from '@/stores/projects'
import { useSettingsStore } from '@/stores/settings'
import NumberInput from './NumberInput.vue'
import type { CollaborationRole } from '@/types'

const emit = defineEmits<{ close: []; created: [] }>()
const { t } = useI18n()
const store = useCommunityStore()
const projectsStore = useProjectsStore()
const settingsStore = useSettingsStore()

const name = ref('')
const selectedProjectId = ref('')
const maxUsers = ref(settingsStore.background.communityMaxUsers)
const defaultRole = ref<CollaborationRole>(settingsStore.background.communityDefaultRole as CollaborationRole)
const loading = ref(false)

async function submit() {
  if (!name.value.trim()) return
  loading.value = true
  try {
    await store.createRoom(name.value, selectedProjectId.value || '', {
      maxUsers: maxUsers.value,
      defaultRole: defaultRole.value,
    })
    emit('created')
  } finally {
    loading.value = false
  }
}

function close() {
  if (!loading.value) emit('close')
}
</script>

<template>
  <div class="dialog-overlay" @click.self="close">
    <div class="dialog">
      <div class="dialog-header">
        <h3>{{ t('community.createRoom') }}</h3>
        <button class="close-btn" :disabled="loading" @click="close">
          <X :size="16" />
        </button>
      </div>
      <div class="dialog-body">
        <label class="field">
          <span>{{ t('community.roomName') }}</span>
          <input v-model="name" type="text" :placeholder="t('community.roomNamePlaceholder')" @keydown.enter="submit" />
        </label>

        <label class="field">
          <span>{{ t('community.project') }}</span>
          <select v-model="selectedProjectId">
            <option value="">{{ t('community.noProject') }}</option>
            <option v-for="p in projectsStore.activeProjects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </label>

        <label class="field">
          <span>{{ t('community.maxUsers') }}</span>
          <NumberInput v-model="maxUsers" :min="1" :max="10" :step="1" variant="stepper" />
        </label>

        <label class="field">
          <span>{{ t('community.defaultRole') }}</span>
          <select v-model="defaultRole">
            <option value="collaborator">{{ t('community.roleCollaborator') }}</option>
            <option value="observer">{{ t('community.roleObserver') }}</option>
          </select>
        </label>
      </div>
      <div class="dialog-footer">
        <button class="btn secondary" :disabled="loading" @click="close">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="loading || !name.trim()" @click="submit">
          {{ loading ? t('common.creating') : t('community.create') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  width: 420px;
  max-width: 90vw;
  background: var(--bg-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
  display: flex;
  flex-direction: column;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.dialog-header h3 {
  margin: 0;
  font-size: 15px;
  color: var(--text-primary);
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  padding: 4px;
  border-radius: 4px;
}

.close-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

.dialog-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.field input,
.field select {
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.field input:focus,
.field select:focus {
  border-color: var(--accent);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-subtle);
}

.btn {
  padding: 7px 14px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn.secondary {
  background: transparent;
  color: var(--text-secondary);
}

.btn.secondary:hover:not(:disabled) {
  background: var(--bg-glass-hover);
}

.btn.primary {
  background: var(--accent);
  color: white;
  border-color: var(--accent);
}

.btn.primary:hover:not(:disabled) {
  opacity: 0.9;
}
</style>
