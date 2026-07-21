<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Users, Plus, LogIn, Copy, Trash2 } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useCommunityStore } from '@/stores/community'
import RoomCreateDialog from './RoomCreateDialog.vue'
import JoinDialog from './JoinDialog.vue'
import InviteDialog from './InviteDialog.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import type { CollaborationRoom } from '@/types'

const { t } = useI18n()
const store = useCommunityStore()

const showCreate = ref(false)
const showJoin = ref(false)
const showInvite = ref(false)
const selectedRoom = ref<CollaborationRoom | null>(null)
const confirmTarget = ref<CollaborationRoom | null>(null)
const initialJoinCode = ref('')

onMounted(() => {
  store.loadRooms()
})

function openCreate() {
  showCreate.value = true
}

const joinDialog = ref<InstanceType<typeof JoinDialog> | null>(null)

function openJoin() {
  showJoin.value = true
}

function openJoinForRoom(room: CollaborationRoom) {
  selectedRoom.value = room
  showJoin.value = true
  // After the dialog mounts, tell it which room was selected
  setTimeout(() => {
    if (joinDialog.value) {
      joinDialog.value.selectRoom(room)
    }
  }, 0)
}

function onRoomCardClick(room: CollaborationRoom) {
  if (store.currentRoom?.id === room.id) {
    store.currentRoom = null
    return
  }
  selectedRoom.value = room
}

function openInvite(room: CollaborationRoom) {
  selectedRoom.value = room
  showInvite.value = true
}

async function handleRoomCreated() {
  showCreate.value = false
  await store.loadRooms()
}

async function handleJoined() {
  showJoin.value = false
  await store.loadRooms()
}

// Re-fetch the room list whenever the side panel gains focus.
// This keeps the active room list in sync after the host leaves
// (which triggers close_room on the backend) or rooms timeout.
let _visibilityInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  store.loadRooms()
  // Poll every 5 seconds so stale rooms disappear from the list
  _visibilityInterval = setInterval(() => {
    store.loadRooms()
  }, 5000)

  // Handle ?join=CODE deep links
  const pendingCode = store.consumePendingJoinCode()
  if (pendingCode) {
    initialJoinCode.value = pendingCode
    showJoin.value = true
  }
})

onUnmounted(() => {
  if (_visibilityInterval) {
    clearInterval(_visibilityInterval)
    _visibilityInterval = null
  }
})

async function handleClose(room: CollaborationRoom) {
  confirmTarget.value = room
}

async function doClose() {
  if (!confirmTarget.value) return
  await store.closeRoom(confirmTarget.value.id)
  confirmTarget.value = null
  await store.loadRooms()
}

function copyInviteCode(code: string) {
  navigator.clipboard.writeText(code)
}
</script>

<template>
  <div class="room-panel">
    <div class="room-actions">
      <button class="room-action-btn" @click="openCreate">
        <Plus :size="14" />
        <span>{{ t('community.createRoom') }}</span>
      </button>
      <button class="room-action-btn" @click="openJoin">
        <LogIn :size="14" />
        <span>{{ t('community.joinRoom') }}</span>
      </button>
    </div>

    <div class="room-section-title">{{ t('community.activeRooms') }}</div>
    <div v-if="store.rooms.length === 0" class="room-empty">
      {{ t('community.noRooms') }}
    </div>
    <div v-else class="room-list">
      <div
        v-for="room in store.rooms"
        :key="room.id"
        class="room-card"
        :class="{ active: store.currentRoom?.id === room.id }"
        @click="store.currentRoom = room"
      >
        <div class="room-card-header">
          <Users :size="14" />
          <span class="room-name">{{ room.name }}</span>
        </div>
        <div class="room-card-meta">
          {{ room.hostAddress }} · {{ room.maxUsers }} {{ t('community.maxUsersUnit') }}
        </div>
        <div class="room-card-code">
          <code>{{ room.inviteCode }}</code>
          <button class="icon-only" :title="t('community.copyInviteCode')" @click.stop="copyInviteCode(room.inviteCode)">
            <Copy :size="12" />
          </button>
        </div>
	        <div class="room-card-actions">
          <button class="text-btn" @click.stop="openJoinForRoom(room)">
            {{ t('community.join') }}
          </button>
          <button class="text-btn" @click.stop="openInvite(room)">
            {{ t('community.invite') }}
          </button>
          <button class="text-btn danger" @click.stop="handleClose(room)">
            <Trash2 :size="12" />
          </button>
        </div>
      </div>
    </div>

    <RoomCreateDialog v-if="showCreate" @close="showCreate = false" @created="handleRoomCreated" />
    <JoinDialog v-if="showJoin" ref="joinDialog" :initial-code="initialJoinCode" @close="showJoin = false" @joined="handleJoined" />
    <InviteDialog v-if="showInvite && selectedRoom" :room="selectedRoom" @close="showInvite = false" />
    <ConfirmDialog
      :visible="!!confirmTarget"
      :title="t('community.confirmCloseRoom')"
      :message="t('community.confirmCloseRoomDesc')"
      @confirm="doClose"
      @cancel="confirmTarget = null"
    />
  </div>
</template>

<style scoped>
.room-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
}

.room-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.room-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-glass);
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition);
}

.room-action-btn:hover {
  background: var(--bg-glass-hover);
  border-color: var(--accent-muted);
}

.room-action-btn:active {
  background: var(--bg-glass-active);
}

.room-section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.room-empty {
  font-size: 12px;
  color: var(--text-tertiary);
  text-align: center;
  padding: 16px 0;
}

.room-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.room-card {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 10px;
  background: var(--bg-glass);
  cursor: pointer;
  transition: all var(--transition);
}

.room-card:hover,
.room-card.active {
  border-color: var(--accent-muted);
  background: var(--bg-glass-hover);
  box-shadow: var(--shadow-sm);
}

.room-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-primary);
  font-size: 13px;
}

.room-name {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.room-card-meta {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

.room-card-code {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.room-card-code code {
  flex: 1;
  background: var(--bg-secondary);
  padding: 4px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  font-size: 12px;
  color: var(--accent);
  letter-spacing: 0.5px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
}

.icon-only {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 4px;
  transition: all var(--transition);
}

.icon-only:hover {
  background: var(--bg-glass-hover);
  color: var(--accent);
}

.room-card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

.text-btn {
  font-size: 11px;
  color: var(--accent);
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all var(--transition);
}

.text-btn:hover {
  background: var(--accent-muted);
  color: var(--accent-hover);
}

.text-btn:active {
  background: var(--bg-glass-active);
}

.text-btn.danger {
  color: var(--danger);
}

.text-btn.danger:hover {
  background: var(--danger-muted);
  color: var(--danger);
}
</style>
