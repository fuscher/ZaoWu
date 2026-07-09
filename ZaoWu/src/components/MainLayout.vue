<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Theme, ViewType } from '@/types'
import CustomTitleBar from './CustomTitleBar.vue'
import ActivityBar from './ActivityBar.vue'
import SidePanel from './SidePanel.vue'
import ChatPanel from './ChatPanel.vue'
import FilePreview from './FilePreview.vue'
import SettingsPanel from './SettingsPanel.vue'
import StatusBar from './StatusBar.vue'
import { useEditorStore } from '@/stores/editor'
import { useI18n } from '@/i18n'

defineProps<{ theme: Theme }>()
const emit = defineEmits<{ toggleTheme: [] }>()

const activeView = ref<ViewType>('chat')
const sideCollapsed = ref(false)
const editorStore = useEditorStore()
const { t } = useI18n()
const clickHint = computed(() => t('filePreview.clickHint'))

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
        <ChatPanel />
      </div>
      <div v-else-if="activeView === 'files' || activeView === 'search'" class="content-area">
        <FilePreview v-if="editorStore.openFilePath" />
        <div v-else class="content-empty">
          <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
            <path d="M4 6h10l3 4h11v14H4V6z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span>{{ clickHint }}</span>
        </div>
      </div>
      <div v-else-if="activeView === 'settings'" class="content-area">
        <SettingsPanel :theme="theme" @toggle-theme="emit('toggleTheme')" />
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

.content-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-tertiary);
  font-size: 13px;
}
</style>
