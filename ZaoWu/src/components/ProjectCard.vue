<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Folder, Users, ChevronRight } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useProjectsStore } from '@/stores/projects'
import FileTree from './FileTree.vue'
import type { Project } from '@/types'

const props = defineProps<{
  project: Project
  batchMode: boolean
  selected: boolean
}>()

const emit = defineEmits<{
  archive: [id: string]
  unarchive: [id: string]
  unload: [id: string]
  delete: [id: string]
}>()

const { t } = useI18n()
const store = useProjectsStore()
const expanded = ref(props.project.virtual === true)
const showMenu = ref(false)
const menuX = ref(0)
const menuY = ref(0)

function toggleExpand() {
  if (props.batchMode) {
    store.toggleBatchSelect(props.project.id)
    return
  }
  expanded.value = !expanded.value
}

function onContextMenu(e: MouseEvent) {
  e.preventDefault()
  if (props.batchMode) return
  showMenu.value = true
  menuX.value = e.clientX
  menuY.value = e.clientY
}

function closeMenu() {
  showMenu.value = false
}

function formatTime(iso: string | null): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

function handleClickOutside(e: MouseEvent) {
  if (showMenu.value) {
    closeMenu()
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div
    class="project-card"
    :class="{ expanded, selected: batchMode && selected, 'batch-mode': batchMode }"
    @click="toggleExpand"
    @contextmenu="onContextMenu"
  >
    <div class="card-header">
      <span class="expand-icon" :class="{ expanded }">
        <ChevronRight :size="14" />
      </span>
      <span class="card-icon">
        <Users v-if="project.virtual" :size="14" class="collab-icon" />
        <Folder v-else :size="14" />
      </span>
      <span class="card-name" :title="project.path">{{ project.name }}</span>
      <span v-if="project.virtual" class="collab-badge">{{ t('projectCard.collaborating') }}</span>
      <span v-if="project.archived" class="archived-badge">{{ t('projectCard.archived') }}</span>
    </div>
    <div v-if="project.lastModified" class="card-meta">
      {{ t('projectCard.lastModified', { time: formatTime(project.lastModified) }) }}
    </div>
    <div v-if="expanded && !project.archived" class="card-tree">
      <FileTree :project-path="project.path" />
    </div>
  </div>

  <Teleport to="body">
    <div v-if="showMenu" class="context-menu" :style="{ left: menuX + 'px', top: menuY + 'px' }">
      <template v-if="project.virtual">
        <div class="menu-item disabled">
          {{ t('projectCard.collabProject') }}
        </div>
      </template>
      <template v-else-if="!project.archived">
        <div class="menu-item" @click="emit('archive', project.id); closeMenu()">
          {{ t('explorer.archive') }}
        </div>
        <div class="menu-item" @click="emit('unload', project.id); closeMenu()">
          {{ t('explorer.unload') }}
        </div>
        <div class="menu-item danger" @click="emit('delete', project.id); closeMenu()">
          {{ t('explorer.delete') }}
        </div>
      </template>
      <template v-else>
        <div class="menu-item" @click="emit('unarchive', project.id); closeMenu()">
          {{ t('explorer.unarchive') }}
        </div>
      </template>
    </div>
  </Teleport>
</template>

<style scoped>
.project-card {
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 2px;
}

.project-card:hover {
  background: var(--bg-glass-hover);
}

.project-card.selected {
  background: var(--accent-muted);
  transform: translateX(5%);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.expand-icon {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  transition: transform 0.15s;
}

.expand-icon.expanded {
  transform: rotate(90deg);
}

.card-icon {
  flex-shrink: 0;
  color: var(--text-tertiary);
  display: flex;
}

.card-name {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

.archived-badge {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}

.collab-badge {
  font-size: 10px;
  color: var(--accent, #4fc3f7);
  background: var(--accent-muted, rgba(79, 195, 247, 0.15));
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}

.collab-icon {
  color: var(--accent, #4fc3f7);
}

.menu-item.disabled {
  color: var(--text-tertiary);
  cursor: default;
  opacity: 0.6;
}

.menu-item.disabled:hover {
  background: transparent;
}

.card-meta {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 4px;
  padding-left: 20px;
}

.card-tree {
  margin-top: 4px;
  padding-left: 8px;
}

.context-menu {
  position: fixed;
  z-index: 10000;
  background: var(--bg-secondary);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 4px;
  min-width: 140px;
  box-shadow: var(--shadow);
}

.menu-item {
  padding: 6px 12px;
  font-size: 13px;
  color: var(--text-primary);
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.menu-item:hover {
  background: var(--bg-glass-hover);
}

.menu-item.danger {
  color: var(--danger);
}

.menu-item.danger:hover {
  background: rgba(255, 95, 86, 0.1);
}
</style>
