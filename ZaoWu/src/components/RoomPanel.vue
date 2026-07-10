<script setup lang="ts">
import { ref, onMounted } from 'vue'
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

onMounted(() => {
  store.loadRooms()
})

function openCreate() {
  showCreate.value = true
}

function openJoin() {
  showJoin.value = true
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
    <JoinDialog v-if="showJoin" @close="showJoin = false" @joined="handleJoined" />
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
  border-radius: 4px;
  font-size: 12px;
  color: var(--accent);
  letter-spacing: 0.5px;
}

.icon-only {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 4px;
}

.icon-only:hover {
  background: var(--bg-glass-hover);
  color: var(--text-secondary);
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
  padding: 2px 4px;
  border-radius: 4px;
}

.text-btn:hover {
  background: var(--accent-muted);
}

.text-btn.danger {
  color: var(--error, #ef4444);
}
</style>
