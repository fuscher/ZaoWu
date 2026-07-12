<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { X, Shield, UserX } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useCommunityStore } from '@/stores/community'
import { DEFAULT_PERMISSIONS } from '@/types'
import type { CollaborationUser, CollaborationRole, PermissionMatrix } from '@/types'

const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const store = useCommunityStore()

const selectedUserId = ref('')
const showKickConfirm = ref(false)

watch(
  () => store.users,
  () => {
    if (!selectedUserId.value && store.users.length > 0) {
      const first = store.users[0]
      if (first) selectedUserId.value = first.id
    }
  },
  { immediate: true },
)

const selectedUser = ref<CollaborationUser | null>(null)

watch(
  selectedUserId,
  (id) => {
    selectedUser.value = store.users.find((u) => u.id === id) || null
  },
  { immediate: true },
)

async function setRole(role: CollaborationRole) {
  if (!selectedUser.value) return
  await store.updateUserRole(selectedUser.value.id, role)
  selectedUser.value = { ...selectedUser.value, role, permissions: DEFAULT_PERMISSIONS[role] }
}

async function togglePermission(key: keyof PermissionMatrix) {
  if (!selectedUser.value || selectedUser.value.role === 'host') return
  const permissions = { ...(selectedUser.value.permissions || DEFAULT_PERMISSIONS[selectedUser.value.role]) }
  permissions[key] = !permissions[key]
  await store.updateUserRole(selectedUser.value.id, selectedUser.value.role, permissions)
  selectedUser.value = { ...selectedUser.value, permissions }
}

function close() {
  emit('close')
}

const canKickUser = computed(() => {
  if (!store.canKick || !selectedUser.value) return false
  if (selectedUser.value.id === store.currentUser?.id) return false
  return true
})

async function confirmKick() {
  if (!selectedUser.value) return
  await store.removeUser(selectedUser.value.id)
  showKickConfirm.value = false
  selectedUserId.value = ''
}

// P2-2: terminal permission is not yet supported — exclude from toggle list
const permissionKeys: (keyof PermissionMatrix)[] = ['edit', 'chat', 'invite', 'kick', 'manageFiles']
</script>

<template>
  <div class="dialog-overlay" @click.self="close">
    <div class="dialog">
      <div class="dialog-header">
        <h3>
          <Shield :size="16" />
          {{ t('community.permissions') }}
        </h3>
        <button class="close-btn" @click="close">
          <X :size="16" />
        </button>
      </div>
      <div class="dialog-body">
        <label class="field">
          <span>{{ t('community.selectUser') }}</span>
          <select v-model="selectedUserId">
            <option v-for="u in store.users" :key="u.id" :value="u.id">{{ u.name }} ({{ t(`community.role${u.role}`) }})</option>
          </select>
        </label>

        <div v-if="selectedUser" class="permission-form">
          <div class="role-row">
            <span class="label">{{ t('community.role') }}</span>
            <div class="role-options">
              <button
                v-for="role in (['collaborator', 'observer'] as CollaborationRole[])"
                :key="role"
                class="role-chip"
                :class="{ active: selectedUser.role === role }"
                :disabled="selectedUser.role === 'host'"
                @click="setRole(role)"
              >
                {{ t(`community.role${role}`) }}
              </button>
            </div>
          </div>

          <div class="permission-list">
            <label v-for="key in permissionKeys" :key="key" class="permission-item">
              <input
                type="checkbox"
                :checked="selectedUser.permissions?.[key] ?? DEFAULT_PERMISSIONS[selectedUser.role][key]"
                :disabled="selectedUser.role === 'host'"
                @change="togglePermission(key)"
              />
              <span>{{ t(`community.permission${key.charAt(0).toUpperCase() + key.slice(1)}`) }}</span>
            </label>
            <label class="permission-item disabled">
              <input type="checkbox" disabled />
              <span>{{ t('community.permissionTerminal') }}</span>
              <span class="unsupported-tag">{{ t('community.unsupported') }}</span>
            </label>
          </div>

          <div v-if="canKickUser" class="kick-section">
            <button class="btn danger" @click="showKickConfirm = true">
              <UserX :size="14" />
              {{ t('community.kickUser') }}
            </button>
          </div>
        </div>
      </div>
      <div class="dialog-footer">
        <button class="btn primary" @click="close">{{ t('common.done') }}</button>
      </div>

      <div v-if="showKickConfirm" class="confirm-overlay" @click.self="showKickConfirm = false">
        <div class="confirm-dialog">
          <p>{{ t('community.kickConfirm', { name: selectedUser?.name ?? '' }) }}</p>
          <div class="confirm-actions">
            <button class="btn" @click="showKickConfirm = false">{{ t('common.cancel') }}</button>
            <button class="btn danger" @click="confirmKick">{{ t('community.kickUser') }}</button>
          </div>
        </div>
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
  display: flex;
  align-items: center;
  gap: 8px;
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

.field select {
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.permission-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.role-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.role-options {
  display: flex;
  gap: 6px;
}

.role-chip {
  padding: 4px 10px;
  border-radius: 12px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
}

.role-chip.active {
  background: var(--accent-muted);
  color: var(--accent);
  border-color: var(--accent-muted);
}

.role-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.permission-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.permission-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
}

.permission-item input:disabled {
  cursor: not-allowed;
}

.permission-item.disabled {
  opacity: 0.5;
  cursor: default;
}

.unsupported-tag {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 1px 5px;
  border-radius: 3px;
  margin-left: auto;
}

.kick-section {
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.btn.danger {
  background: transparent;
  color: var(--danger, #ff5f56);
  border-color: var(--danger, #ff5f56);
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn.danger:hover {
  background: rgba(255, 95, 86, 0.1);
}

.confirm-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  z-index: 10;
}

.confirm-dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 16px;
  width: 280px;
  text-align: center;
}

.confirm-dialog p {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--text-primary);
}

.confirm-actions {
  display: flex;
  gap: 8px;
  justify-content: center;
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

.btn.primary {
  background: var(--accent);
  color: white;
  border-color: var(--accent);
}

.btn.primary:hover {
  opacity: 0.9;
}
</style>
