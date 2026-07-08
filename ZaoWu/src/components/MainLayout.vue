<script setup lang="ts">
import { ref } from 'vue'
import type { Theme, ViewType } from '@/types'
import CustomTitleBar from './CustomTitleBar.vue'
import ActivityBar from './ActivityBar.vue'
import SidePanel from './SidePanel.vue'
import ChatMessages from './ChatMessages.vue'
import ChatInput from './ChatInput.vue'
import StatusBar from './StatusBar.vue'

defineProps<{ theme: Theme }>()
const emit = defineEmits<{ toggleTheme: [] }>()

const activeView = ref<ViewType>('chat')
const sideCollapsed = ref(false)

function selectView(view: ViewType) {
  if (view === activeView.value) {
    sideCollapsed.value = !sideCollapsed.value
  } else {
    activeView.value = view
    sideCollapsed.value = false
  }
}
</script>

<template>
  <div class="main-layout">
    <CustomTitleBar />
    <div class="body">
      <ActivityBar :active-view="activeView" :theme="theme" @select="selectView" @toggle-theme="emit('toggleTheme')" />
      <SidePanel :view="activeView" :collapsed="sideCollapsed" @toggle="sideCollapsed = !sideCollapsed" />
      <div v-if="activeView === 'chat'" class="content-area">
        <ChatMessages />
        <ChatInput />
      </div>
    </div>
    <StatusBar />
  </div>
</template>

<style scoped>
.main-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  -webkit-app-region: no-drag;
}

.body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.content-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
</style>
