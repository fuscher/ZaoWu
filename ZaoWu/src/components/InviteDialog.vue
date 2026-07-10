<script setup lang="ts">
import { ref, computed } from 'vue'
import { X, Copy, RefreshCw } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useCommunityStore } from '@/stores/community'
import type { CollaborationRoom } from '@/types'

const props = defineProps<{ room: CollaborationRoom }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const store = useCommunityStore()

const copied = ref(false)

const inviteLink = computed(() => {
  const host = props.room.hostAddress || window.location.host
  return `zaowu://join?host=${encodeURIComponent(host)}&room=${encodeURIComponent(props.room.id)}&token=${encodeURIComponent(props.room.inviteCode)}`
})

async function refresh() {
  await store.refreshInviteCode()
}

function copy(text: string) {
  navigator.clipboard.writeText(text)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

function close() {
  emit('close')
}
</script>

<template>
  <div class="dialog-overlay" @click.self="close">
    <div class="dialog">
      <div class="dialog-header">
        <h3>{{ t('community.invite') }}</h3>
        <button class="close-btn" @click="close">
          <X :size="16" />
        </button>
      </div>
      <div class="dialog-body">
        <div class="field">
          <span>{{ t('community.inviteCode') }}</span>
          <div class="copy-row">
            <code>{{ room.inviteCode }}</code>
            <button class="icon-btn" :title="t('community.copy')" @click="copy(room.inviteCode)">
              <Copy :size="14" />
            </button>
            <button v-if="store.isHost" class="icon-btn" :title="t('community.refreshInviteCode')" @click="refresh">
              <RefreshCw :size="14" />
            </button>
          </div>
        </div>
        <div class="field">
          <span>{{ t('community.inviteLink') }}</span>
          <div class="copy-row">
            <input :value="inviteLink" readonly />
            <button class="icon-btn" :title="t('community.copy')" @click="copy(inviteLink)">
              <Copy :size="14" />
            </button>
          </div>
        </div>
        <div class="field">
          <span>{{ t('community.hostAddress') }}</span>
          <div class="copy-row">
            <input :value="room.hostAddress" readonly />
            <button class="icon-btn" :title="t('community.copy')" @click="copy(room.hostAddress)">
              <Copy :size="14" />
            </button>
          </div>
        </div>
        <div v-if="copied" class="copied-hint">{{ t('community.copied') }}</div>
      </div>
      <div class="dialog-footer">
        <button class="btn primary" @click="close">{{ t('common.done') }}</button>
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
  width: 460px;
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

.copy-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.copy-row code,
.copy-row input {
  flex: 1;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 12px;
  font-family: monospace;
  outline: none;
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: var(--bg-glass);
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 6px;
}

.icon-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
}

.copied-hint {
  font-size: 12px;
  color: var(--success, #10b981);
  text-align: center;
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
