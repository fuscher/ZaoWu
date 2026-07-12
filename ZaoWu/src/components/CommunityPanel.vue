<script setup lang="ts">
import { ref, shallowRef, watch, computed, onMounted, onUnmounted } from 'vue'
import { Users, MessageSquare, Shield, LogOut, Wifi, WifiOff, Link } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useCommunityStore } from '@/stores/community'
import { useEditorStore } from '@/stores/editor'
import { useCollaboration } from '@/composables/useCollaboration'
import CollabEditor from './CollabEditor.vue'
import CommunityChatPanel from './CommunityChatPanel.vue'
import UserPresence from './UserPresence.vue'
import InviteDialog from './InviteDialog.vue'
import PermissionPanel from './PermissionPanel.vue'

const { t } = useI18n()
const store = useCommunityStore()
const editorStore = useEditorStore()

const showInvite = ref(false)
const showPermissions = ref(false)

const _watching = ref(false)
const _collab = shallowRef<ReturnType<typeof useCollaboration> | null>(null)
const _isMounted = ref(true)

const collab = computed(() => {
  if (!store.currentRoom || !store.currentUser || !store.wsUrl) {
    return null
  }
  if (!_isMounted.value) return null
  if (_collab.value) return _collab.value
  const c = useCollaboration({
    roomId: store.currentRoom.id,
    userId: store.currentUser.id,
    wsUrl: store.wsUrl,
    userName: store.currentUser.name,
    userColor: store.currentUser.color,
  })
  c.connect()
  store.setConnectionStatus(c.status.value)
  _collab.value = c
  _watching.value = true
  return c
})

watch(
  () => [store.currentRoom?.id, store.currentUser?.id, store.wsUrl] as const,
  ([roomId, userId, url], [oldRoomId, oldUserId, oldUrl]) => {
    // Only destroy on actual transitions (e.g. joining a different room),
    // NOT on initial population from null to a value.
    if (!_watching.value) return
    const changed =
      (oldRoomId && oldRoomId !== roomId) ||
      (oldUserId && oldUserId !== userId) ||
      (oldUrl && oldUrl !== url)
    if (changed && _collab.value) {
      _collab.value.disconnect()
      _collab.value = null
    }
  },
)

watch(
  () => _collab.value?.status.value,
  (status) => {
    if (status) store.setConnectionStatus(status)
  },
)

watch(
  () => _collab.value?.users.value,
  (users) => {
    if (users) store.updateUsers(users)
  },
  { deep: true },
)

// Bridge editor save → collaboration sendFileDiff
watch(
  () => _collab.value,
  (collabInstance) => {
    if (collabInstance) {
      editorStore.onFileSaved = (path: string, content: string) => {
        const virtualProj = store.currentRoom
        if (!virtualProj) return
        collabInstance.sendFileDiff(path, content, 'write')
      }
    } else {
      editorStore.onFileSaved = null
    }
  },
)

// Bridge editor openFile → collaboration updateCursor (P1-1)
watch(
  () => editorStore.openFilePath,
  (filePath) => {
    if (_collab.value && filePath) {
      _collab.value.updateCursor({ filePath, line: 0, column: 0 })
    }
  },
)

// P2-1: Listen for file operations from FileTreeNode context menu
function handleCollabFileOperation(e: Event) {
  const detail = (e as CustomEvent).detail as { operation: string; path: string; content?: string; oldPath?: string; newPath?: string }
  if (!_collab.value) return
  if (detail.operation === 'write') {
    _collab.value.sendFileDiff(detail.path, detail.content || '', 'write')
  } else if (detail.operation === 'delete') {
    _collab.value.sendFileDiff(detail.path, '', 'delete')
  } else if (detail.operation === 'rename' && detail.oldPath && detail.newPath) {
    _collab.value.sendFileDiff(detail.oldPath, '', 'rename', { oldPath: detail.oldPath, newPath: detail.newPath })
    // Update editor path if the renamed file is currently open
    const normOld = detail.oldPath.replace(/\\/g, '/')
    const normCurrent = (editorStore.openFilePath || '').replace(/\\/g, '/')
    if (normCurrent === normOld || normCurrent.endsWith(normOld)) {
      editorStore.openFile(detail.newPath)
    }
  }
  // Dispatch file-diff event for local FileTree refresh
  window.dispatchEvent(new CustomEvent('collab-file-diff', {
    detail: { path: detail.path, operation: detail.operation }
  }))
}

onMounted(() => {
  window.addEventListener('collab-file-operation', handleCollabFileOperation)
})

onUnmounted(() => {
  window.removeEventListener('collab-file-operation', handleCollabFileOperation)
})

onUnmounted(() => {
  _isMounted.value = false
  if (_collab.value) {
    _collab.value.disconnect()
    _collab.value = null
  }
  _watching.value = false
})

async function leave() {
  collab.value?.disconnect()
  await store.leaveRoom()
}

function copyInviteLink() {
  if (!store.currentRoom) return
  const link = `zaowu://join?host=${encodeURIComponent(store.currentRoom.hostAddress)}&room=${encodeURIComponent(store.currentRoom.id)}&token=${encodeURIComponent(store.currentRoom.inviteCode)}`
  navigator.clipboard.writeText(link)
}
</script>

<template>
  <div class="community-panel">
    <div v-if="!store.currentRoom" class="community-empty">
      <Users :size="48" />
      <h3>{{ t('community.welcomeTitle') }}</h3>
      <p>{{ t('community.welcomeDesc') }}</p>
      <div class="empty-actions">
        <span class="hint">{{ t('community.useSidePanelHint') }}</span>
      </div>
    </div>

    <template v-else>
      <div class="community-toolbar">
        <div class="toolbar-left">
          <span class="room-title">{{ store.currentRoom.name }}</span>
          <span class="connection-badge" :class="store.connectionStatus">
            <Wifi v-if="store.connectionStatus === 'connected'" :size="12" />
            <WifiOff v-else :size="12" />
            {{ t(`community.status${store.connectionStatus}`) }}
          </span>
        </div>
        <div class="toolbar-right">
          <UserPresence :users="[...(store.currentUser ? [store.currentUser] : []), ...store.users]" :current-user-id="store.currentUser?.id" />
          <button class="tool-btn" :title="t('community.copyInviteLink')" @click="copyInviteLink">
            <Link :size="14" />
          </button>
          <button class="tool-btn" :title="t('community.invite')" @click="showInvite = true">
            <MessageSquare :size="14" />
          </button>
          <button v-if="store.isHost" class="tool-btn" :title="t('community.permissions')" @click="showPermissions = true">
            <Shield :size="14" />
          </button>
          <button class="tool-btn danger" :title="t('community.leaveRoom')" @click="leave">
            <LogOut :size="14" />
          </button>
        </div>
      </div>

      <div class="community-body">
        <div class="editor-area">
          <CollabEditor
            v-if="collab"
            :ytext="collab.doc.getText('codemirror')"
            :awareness="collab.awareness"
            file-name="collab.txt"
            :readonly="!store.canEdit"
          />
        </div>
        <CommunityChatPanel
          v-if="collab"
          :messages="collab.chatMessages"
          :users="[...(store.currentUser ? [store.currentUser] : []), ...store.users]"
          :current-user-id="store.currentUser?.id || ''"
          @send="collab.sendChatMessage"
        />
      </div>
    </template>

    <InviteDialog v-if="showInvite && store.currentRoom" :room="store.currentRoom" @close="showInvite = false" />
    <PermissionPanel v-if="showPermissions" @close="showPermissions = false" />
  </div>
</template>

<style scoped>
.community-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg-primary);
}

.community-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-tertiary);
  text-align: center;
  padding: 24px;
}

.community-empty h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
}

.community-empty p {
  margin: 0;
  font-size: 13px;
  max-width: 320px;
}

.empty-actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}

.community-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
  flex-shrink: 0;
  gap: 12px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.room-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.connection-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-glass);
  color: var(--text-tertiary);
  text-transform: capitalize;
}

.connection-badge.connected {
  background: var(--accent-muted);
  color: var(--accent);
}

.connection-badge.connecting,
.connection-badge.reconnecting {
  background: rgba(255, 189, 46, 0.15);
  color: var(--warning);
}

.connection-badge.error,
.connection-badge.disconnected {
  background: rgba(255, 95, 86, 0.15);
  color: var(--danger);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all var(--transition);
}

.tool-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--accent);
}

.tool-btn:active {
  background: var(--bg-glass-active);
}

.tool-btn.danger:hover {
  background: rgba(255, 95, 86, 0.15);
  color: var(--danger);
}

.community-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.editor-area {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.btn {
  padding: 8px 16px;
  border-radius: 8px;
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

.btn.secondary {
  background: transparent;
  color: var(--text-secondary);
}

.btn.secondary:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.btn.primary:active,
.btn.secondary:active {
  transform: scale(0.97);
}
</style>
