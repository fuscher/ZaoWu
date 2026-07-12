<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import FileTreeNode from './FileTreeNode.vue'
import type { TreeNode } from '@/types'

const props = defineProps<{
  projectPath: string
}>()

const tree = ref<TreeNode[]>([])
const loading = ref(false)

async function loadTree(path?: string) {
  const targetPath = path || props.projectPath
  loading.value = true
  try {
    const res = await fetch('/api/explorer/get-tree', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: targetPath, depth: 1 }),
    })
    const data = await res.json()
    if (data.ok) {
      if (!path) {
        tree.value = data.tree || []
      } else {
        updateTreeNode(tree.value, path, data.tree || [])
      }
    }
  } catch {
    // ignore
  } finally {
    loading.value = false
  }
}

function updateTreeNode(nodes: TreeNode[], targetPath: string, children: TreeNode[]): boolean {
  for (const node of nodes) {
    if (node.path === targetPath) {
      node.children = children
      return true
    }
    if (node.children && updateTreeNode(node.children, targetPath, children)) {
      return true
    }
  }
  return false
}

function loadChildren(path: string) {
  loadTree(path)
}

function handleCollabFileDiff(e: Event) {
  const detail = (e as CustomEvent).detail as { path: string; operation: string }
  // Only reload if the diff path is within this project's directory
  const normProject = props.projectPath.replace(/\\/g, '/')
  const normDiff = detail.path.replace(/\\/g, '/')
  if (normProject && (normDiff.startsWith(normProject) || normProject.endsWith(normDiff))) {
    loadTree()
  }
}

onMounted(() => {
  loadTree()
  window.addEventListener('collab-file-diff', handleCollabFileDiff)
})

onUnmounted(() => {
  window.removeEventListener('collab-file-diff', handleCollabFileDiff)
})
</script>

<template>
  <div class="file-tree">
    <div v-if="loading && tree.length === 0" class="tree-loading">
      <svg width="14" height="14" viewBox="0 0 14 14" class="spin">
        <circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.5" fill="none" stroke-dasharray="20 12"/>
      </svg>
    </div>
    <FileTreeNode
      v-for="node in tree"
      :key="node.path"
      :node="node"
      :level="0"
      @load-children="loadChildren"
    />
  </div>
</template>

<style scoped>
.file-tree {
  padding: 4px 0;
}

.tree-loading {
  display: flex;
  justify-content: center;
  padding: 12px;
  color: var(--text-tertiary);
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
