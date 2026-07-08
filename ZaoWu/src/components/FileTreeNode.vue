<script setup lang="ts">
import { ref } from 'vue'
import { Folder, FolderOpen, File } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { TreeNode } from '@/types'

const props = defineProps<{
  node: TreeNode
  level: number
}>()

const emit = defineEmits<{ 'load-children': [path: string] }>()
const { t } = useI18n()
const expanded = ref(false)
const loading = ref(false)

function toggle() {
  if (props.node.type !== 'directory') return

  if (!expanded.value && props.node.children === undefined) {
    loading.value = true
    emit('load-children', props.node.path)
    setTimeout(() => {
      loading.value = false
      expanded.value = true
    }, 100)
    return
  }

  expanded.value = !expanded.value
}

function onChildLoad(path: string) {
  emit('load-children', path)
}
</script>

<template>
  <div class="tree-node">
    <div
      class="node-row"
      :style="{ paddingLeft: level * 16 + 'px' }"
      @click="toggle"
    >
      <span class="node-arrow" :class="{ expanded, visible: node.type === 'directory' }">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M4 3l4 3-4 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </span>
      <span class="node-icon">
        <FolderOpen v-if="node.type === 'directory' && expanded" :size="14" />
        <Folder v-else-if="node.type === 'directory'" :size="14" />
        <File v-else :size="14" />
      </span>
      <span class="node-name" :title="node.path">{{ node.name }}</span>
      <span v-if="loading" class="node-loading">
        <svg width="12" height="12" viewBox="0 0 12 12" class="spin">
          <circle cx="6" cy="6" r="5" stroke="currentColor" stroke-width="1.5" fill="none" stroke-dasharray="20 12"/>
        </svg>
      </span>
    </div>
    <div v-if="node.type === 'directory' && expanded && node.children" class="node-children">
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
</style>
