<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { Theme, ViewType } from '@/types'
import CustomTitleBar from './CustomTitleBar.vue'
import ActivityBar from './ActivityBar.vue'
import SidePanel from './SidePanel.vue'
import ChatPanel from './ChatPanel.vue'
import FilePreview from './FilePreview.vue'
import SettingsPanel from './SettingsPanel.vue'
import GitPanel from './GitPanel.vue'
import CommunityPanel from './CommunityPanel.vue'
import PluginManagementDetail from './PluginManagementDetail.vue'
import StatusBar from './StatusBar.vue'
import { useEditorStore } from '@/stores/editor'
import { useCommunityStore } from '@/stores/community'
import { useI18n } from '@/i18n'
import { pluginEventBus } from '@/plugin-system/events'

defineProps<{ theme: Theme }>()
const emit = defineEmits<{ toggleTheme: [] }>()

const activeView = ref<ViewType>('chat')
const sideCollapsed = ref(false)
const highlightSection = ref<string | null>(null)
const selectedPluginName = ref<string | null>(null)
const editorStore = useEditorStore()
const communityStore = useCommunityStore()
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

function handleHighlightSection(section: string | null) {
  highlightSection.value = section
}

function handleShowPluginDetail(pluginName: string) {
  selectedPluginName.value = pluginName
}

// 监听插件 activity bar action handler 事件
onMounted(() => {
  pluginEventBus.on('hello_world.click', () => {
    activeView.value = 'plugins'
    sideCollapsed.value = false
  })

  // Handle shared HTTP join links such as http://host/?join=ABCDEF
  const joinCode = (window as any).__JOIN_CODE__
  if (joinCode && typeof joinCode === 'string') {
    communityStore.pendingJoinCode = joinCode
    activeView.value = 'community'
    sideCollapsed.value = false
  }
})
</script>

<template>
  <div class="main-layout">
    <CustomTitleBar />
    <div class="body">
      <ActivityBar :active-view="activeView" :theme="theme" @select="selectView" @toggle-theme="emit('toggleTheme')" />
      <SidePanel :view="activeView" :collapsed="sideCollapsed" @toggle="sideCollapsed = !sideCollapsed" @highlight-section="handleHighlightSection" @show-plugin-detail="handleShowPluginDetail" />
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
        <SettingsPanel :theme="theme" :highlight-section="highlightSection" @toggle-theme="emit('toggleTheme')" @highlight="handleHighlightSection" />
      </div>
      <div v-else-if="activeView === 'git'" class="content-area">
        <GitPanel />
      </div>
      <div v-else-if="activeView === 'community'" class="content-area">
        <CommunityPanel />
      </div>
      <div v-else-if="activeView === 'plugins'" class="content-area">
        <PluginManagementDetail :plugin-name="selectedPluginName" />
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
