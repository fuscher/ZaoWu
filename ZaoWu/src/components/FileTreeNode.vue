<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { Folder, FolderOpen, File } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useEditorStore } from '@/stores/editor'
import { useProjectsStore } from '@/stores/projects'
import type { TreeNode } from '@/types'

const props = defineProps<{
  node: TreeNode
  level: number
}>()

const emit = defineEmits<{ 'load-children': [path: string] }>()
const { t } = useI18n()
const editorStore = useEditorStore()
const projectsStore = useProjectsStore()
const expanded = ref(false)
const loading = ref(false)
const showMenu = ref(false)
const menuX = ref(0)
const menuY = ref(0)
const isRenaming = ref(false)
const renameValue = ref('')
const renameInput = ref<HTMLInputElement | null>(null)

const isExpandable = computed(() => props.node.type === 'directory')

// Check if this node is inside a virtual (collaboration) project
const isVirtualProject = computed(() => {
  const normPath = props.node.path.replace(/\\/g, '/')
  return projectsStore.virtualProjects.some((vp) => {
    const normVpPath = vp.path.replace(/\\/g, '/')
    return normPath.startsWith(normVpPath)
  })
})

watch(() => props.node.children, (newChildren) => {
  if (loading.value && newChildren !== undefined) {
    loading.value = false
    expanded.value = true
  }
})

function toggle() {
  if (props.node.type === 'file') {
    editorStore.openFile(props.node.path)
    return
  }

  if (props.node.children !== undefined) {
    expanded.value = !expanded.value
    return
  }

  if (loading.value) return

  if (!expanded.value) {
    loading.value = true
    emit('load-children', props.node.path)
  } else {
    expanded.value = false
  }
}

function onChildLoad(path: string) {
  emit('load-children', path)
}

function onContextMenu(e: MouseEvent) {
  if (!isVirtualProject.value) return
  e.preventDefault()
  e.stopPropagation()
  showMenu.value = true
  menuX.value = e.clientX
  menuY.value = e.clientY
}

function closeMenu() {
  showMenu.value = false
}

function handleNewFile() {
  closeMenu()
  const fileName = window.prompt(t('fileTree.newFileNamePrompt'))
  if (!fileName) return
  const parentDir = props.node.type === 'directory' ? props.node.path : props.node.path.replace(/[\\/][^\\/]+$/, '')
  const newPath = parentDir + '/' + fileName
  // Create empty file via API, then broadcast via collab event
  fetch('/api/explorer/save-file', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: newPath, content: '' }),
  }).then(() => {
    window.dispatchEvent(new CustomEvent('collab-file-operation', {
      detail: { operation: 'write', path: newPath, content: '' }
    }))
  })
}

function handleDelete() {
  closeMenu()
  if (!window.confirm(t('fileTree.confirmDelete', { name: props.node.name }))) return
  window.dispatchEvent(new CustomEvent('collab-file-operation', {
    detail: { operation: 'delete', path: props.node.path }
  }))
}

function handleRename() {
  closeMenu()
  isRenaming.value = true
  renameValue.value = props.node.name
  // Focus the input on next tick
  setTimeout(() => {
    renameInput.value?.focus()
    renameInput.value?.select()
  }, 0)
}

function commitRename() {
  if (!isRenaming.value) return
  const newName = renameValue.value.trim()
  if (!newName || newName === props.node.name) {
    isRenaming.value = false
    return
  }
  const oldPath = props.node.path
  const parentDir = oldPath.replace(/[\\/][^\\/]+$/, '')
  const newPath = parentDir + '/' + newName
  isRenaming.value = false
  window.dispatchEvent(new CustomEvent('collab-file-operation', {
    detail: { operation: 'rename', path: newPath, oldPath, newPath }
  }))
}

function cancelRename() {
  isRenaming.value = false
}

function handleClickOutside() {
  if (showMenu.value) closeMenu()
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="tree-node">
    <div
      class="node-row"
      :style="{ paddingLeft: level * 16 + 'px' }"
      @click.stop="toggle"
      @contextmenu="onContextMenu"
    >
      <span class="node-arrow" :class="{ expanded, visible: isExpandable }">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M4 3l4 3-4 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </span>
      <span class="node-icon">
        <FolderOpen v-if="isExpandable && expanded" :size="14" />
        <Folder v-else-if="isExpandable" :size="14" />
        <File v-else :size="14" />
      </span>
      <span v-if="!isRenaming" class="node-name" :title="node.path">{{ node.name }}</span>
      <input
        v-else
        ref="renameInput"
        v-model="renameValue"
        class="rename-input"
        @click.stop
        @keyup.enter="commitRename"
        @keyup.escape="cancelRename"
        @blur="commitRename"
      />
      <span v-if="loading" class="node-loading">
        <svg width="12" height="12" viewBox="0 0 12 12" class="spin">
          <circle cx="6" cy="6" r="5" stroke="currentColor" stroke-width="1.5" fill="none" stroke-dasharray="20 12"/>
        </svg>
      </span>
    </div>
    <div v-if="isExpandable && expanded && node.children" class="node-children">
      <div v-if="node.children.length === 0" class="empty-hint" :style="{ paddingLeft: (level + 1) * 16 + 28 + 'px' }">
        {{ t('fileTree.empty') }}
      </div>
      <FileTreeNode
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :level="level + 1"
        @load-children="onChildLoad"
      />
    </div>
  </div>

  <Teleport to="body">
    <div v-if="showMenu" class="ctx-menu" :style="{ left: menuX + 'px', top: menuY + 'px' }" @click.stop>
      <div v-if="isExpandable" class="ctx-item" @click="handleNewFile">
        {{ t('fileTree.newFile') }}
      </div>
      <div class="ctx-item" @click="handleRename">
        {{ t('fileTree.rename') }}
      </div>
      <div class="ctx-item danger" @click="handleDelete">
        {{ t('fileTree.delete') }}
      </div>
    </div>
    <div v-if="showMenu" class="ctx-overlay" @click="closeMenu" @contextmenu.prevent="closeMenu" />
  </Teleport>
</template>

<style scoped>
.node-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
  min-height: 26px;
}

.node-row:hover {
  background: var(--bg-glass-hover);
}

.node-arrow {
  flex-shrink: 0;
  width: 12px;
  height: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  transition: transform 0.15s;
  visibility: hidden;
}

.node-arrow.visible {
  visibility: visible;
}

.node-arrow.expanded {
  transform: rotate(90deg);
}

.node-icon {
  flex-shrink: 0;
  color: var(--text-tertiary);
  display: flex;
}

.node-name {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

.rename-input {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  padding: 2px 4px;
  border: 1px solid var(--accent, #4fc3f7);
  border-radius: 3px;
  background: var(--bg-primary);
  color: var(--text-primary);
  outline: none;
}

.node-loading {
  flex-shrink: 0;
  color: var(--text-tertiary);
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.empty-hint {
  font-size: 11px;
  color: var(--text-tertiary);
  padding: 4px 8px;
}

.node-children {
  overflow: hidden;
}

.ctx-menu {
  position: fixed;
  z-index: 10000;
  background: var(--bg-secondary);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 4px;
  min-width: 120px;
  box-shadow: var(--shadow);
}

.ctx-item {
  padding: 6px 12px;
  font-size: 13px;
  color: var(--text-primary);
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.ctx-item:hover {
  background: var(--bg-glass-hover);
}

.ctx-item.danger {
  color: var(--danger, #ff5f56);
}

.ctx-item.danger:hover {
  background: rgba(255, 95, 86, 0.1);
}

.ctx-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
}
</style>
