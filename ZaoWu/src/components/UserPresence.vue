<script setup lang="ts">
import { computed } from 'vue'
import type { CollaborationUser } from '@/types'

const props = defineProps<{
  users: CollaborationUser[]
  currentUserId?: string
}>()

const displayUsers = computed(() => props.users.filter((u) => u.status === 'online'))
</script>

<template>
  <div class="user-presence">
    <div
      v-for="user in displayUsers"
      :key="user.id"
      class="user-avatar"
      :style="{ backgroundColor: user.color }"
      :title="`${user.name}${user.id === currentUserId ? ' (you)' : ''}`"
    >
      {{ user.name.charAt(0).toUpperCase() }}
    </div>
  </div>
</template>

<style scoped>
.user-presence {
  display: flex;
  align-items: center;
  gap: 4px;
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
}

.user-avatar:first-child {
  margin-left: 0;
}
</style>
