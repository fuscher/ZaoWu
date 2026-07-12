<script setup lang="ts">
import { computed } from 'vue'
import type { CollaborationUser } from '@/types'

const props = defineProps<{
  users: CollaborationUser[]
  currentUserId?: string
}>()

const displayUsers = computed(() => props.users.filter((u) => u.status === 'online'))

function fileBasename(path: string | undefined): string {
  if (!path) return ''
  return path.replace(/\\/g, '/').split('/').pop() || path
}
</script>

<template>
  <div class="user-presence">
    <div
      v-for="user in displayUsers"
      :key="user.id"
      class="user-item"
    >
      <div
        class="user-avatar"
        :style="{ backgroundColor: user.color }"
        :title="user.cursor?.filePath
          ? `${user.name} → ${fileBasename(user.cursor.filePath)}`
          : `${user.name}${user.id === currentUserId ? ' (you)' : ''}`"
      >
        {{ user.name.charAt(0).toUpperCase() }}
      </div>
      <span v-if="user.cursor?.filePath" class="user-file">
        {{ fileBasename(user.cursor.filePath) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.user-presence {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.user-item {
  display: flex;
  align-items: center;
  gap: 3px;
}

.user-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 600;
  color: white;
  border: 2px solid var(--bg-secondary);
  margin-left: -6px;
  flex-shrink: 0;
}

.user-avatar:first-child {
  margin-left: 0;
}

.user-file {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 1px 5px;
  border-radius: 3px;
  white-space: nowrap;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
