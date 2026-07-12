<script setup lang="ts">
import { ref, computed } from 'vue'
import { X } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useCommunityStore } from '@/stores/community'
import type { CollaborationRoom } from '@/types'

const emit = defineEmits<{ close: []; joined: [] }>()
const { t } = useI18n()
const store = useCommunityStore()

const inviteLink = ref('')
const userName = ref('')
const loading = ref(false)
const error = ref('')
const selectedRoom = ref<CollaborationRoom | null>(null)

// When the user clicks a room card in the side panel before clicking "Join",
// this sets the selected room and auto-fills the invite code.
function selectRoom(room: CollaborationRoom | null) {
  selectedRoom.value = room
  if (room && room.inviteCode) {
    inviteLink.value = `${room.id}:${room.inviteCode}`
  }
}

defineExpose({ selectRoom })

const parsed = computed(() => {
  const link = inviteLink.value.trim()
  if (!link) {
    // If a room was pre-selected but the user cleared the input,
    // still use the selected room's data.
    if (selectedRoom.value?.inviteCode) {
      return {
        roomId: selectedRoom.value.id,
        inviteCode: selectedRoom.value.inviteCode,
      }
    }
    return null
  }

  // zaowu://join?host=...&room=...&token=...
  if (link.startsWith('zaowu://')) {
    try {
      const url = new URL(link.replace('zaowu://', 'http://'))
      const roomId = url.searchParams.get('room') || ''
      const code = url.searchParams.get('token') || ''
      if (roomId && code) return { roomId, inviteCode: code }
    } catch {
      // fall through
    }
  }

  // "roomId:inviteCode" with colon separator (UUIDs contain hyphens, not colons)
  const colonIdx = link.indexOf(':')
  if (colonIdx > 0 && colonIdx < link.length - 1 && link.slice(colonIdx + 1).length <= 8) {
    // The part after the last colon is short (6-8 chars = invite code)
    return {
      roomId: link.slice(0, colonIdx).trim(),
      inviteCode: link.slice(colonIdx + 1).trim().toUpperCase(),
    }
  }

  // "roomId inviteCode" with whitespace separator
  const whitespaceMatch = link.match(/^(.+)\s+([A-Za-z0-9]{6,8})$/)
  if (whitespaceMatch) {
    return {
      roomId: whitespaceMatch[1]!.trim(),
      inviteCode: whitespaceMatch[2]!.trim().toUpperCase(),
    }
  }

  // Plain invite code (6-8 uppercase alphanumeric) — works when room was pre-selected
  const plainCodeMatch = link.match(/^[A-Za-z0-9]{6,8}$/)
  if (plainCodeMatch && selectedRoom.value) {
    return {
      roomId: selectedRoom.value.id,
      inviteCode: link.toUpperCase(),
    }
  }

  return null
})

async function submit() {
  if (!parsed.value?.roomId || !parsed.value?.inviteCode) {
    error.value = t('community.invalidInviteLink')
    return
  }
  loading.value = true
  error.value = ''
  try {
    await store.joinRoom(parsed.value.roomId, parsed.value.inviteCode, userName.value || t('community.anonymous'))
    emit('joined')
  } catch (err) {
    error.value = String(err)
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
        <h3>{{ t('community.joinRoom') }}</h3>
        <button class="close-btn" :disabled="loading" @click="close">
          <X :size="16" />
        </button>
      </div>
      <div class="dialog-body">
        <label class="field">
          <span>{{ t('community.inviteLinkOrCode') }}</span>
          <input v-model="inviteLink" type="text" :placeholder="t('community.inviteLinkPlaceholder')" @keydown.enter="submit" />
        </label>
        <label class="field">
          <span>{{ t('community.yourName') }}</span>
          <input v-model="userName" type="text" :placeholder="t('community.yourNamePlaceholder')" @keydown.enter="submit" />
        </label>
        <div v-if="error" class="error">{{ error }}</div>
      </div>
      <div class="dialog-footer">
        <button class="btn secondary" :disabled="loading" @click="close">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="loading || !parsed" @click="submit">
          {{ loading ? t('common.joining') : t('community.join') }}
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

.field input {
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.field input:focus {
  border-color: var(--accent);
}

.error {
  font-size: 12px;
  color: var(--danger);
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
