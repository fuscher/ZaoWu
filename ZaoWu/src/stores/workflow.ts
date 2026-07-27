import { ref, computed, type Ref } from 'vue'
import { defineStore } from 'pinia'
import type {
  WorkflowDefinition,
  WorkflowNode,
  WorkflowEdge,
  NodeStatus,
} from '@/types/workflow'

export interface NodeRuntimeInfo {
  status: NodeStatus
  inputs?: Record<string, unknown>
  outputs?: Record<string, unknown>
  tokens?: number
  elapsedMs?: number
  error?: string
}

export const useWorkflowStore = defineStore('workflow', () => {
  const workflow = ref<WorkflowDefinition | null>(null)
  const selectedNodeIds = ref<string[]>([])
  const nodeRuntime = ref<Record<string, NodeRuntimeInfo>>({})
  const activeRunId = ref<string | null>(null)
  const isDirty = ref(false)
  let lastSavedSnapshot = ''

  // ── 撤销 / 重做 ──
  const historyVersion = ref(0)
  const historyStack: Ref<string[]> = ref([])
  const historyIndex = ref(-1)

  function commitHistory() {
    if (!workflow.value) return
    // 丢弃当前位置之后的历史（新操作覆盖未来分支）
    historyStack.value = historyStack.value.slice(0, historyIndex.value + 1)
    historyStack.value.push(JSON.stringify({
      nodes: workflow.value.nodes,
      edges: workflow.value.edges,
      name: workflow.value.name,
    }))
    historyIndex.value = historyStack.value.length - 1
    // 保留最近 50 条，裁剪旧记录
    if (historyStack.value.length > 50) {
      historyStack.value = historyStack.value.slice(historyStack.value.length - 50)
      historyIndex.value = historyStack.value.length - 1
    }
  }

  function undo() {
    if (historyIndex.value <= 0 || !workflow.value) return
    historyIndex.value--
    _applyHistorySnapshot()
    historyVersion.value++
  }

  function redo() {
    if (historyIndex.value >= historyStack.value.length - 1 || !workflow.value) return
    historyIndex.value++
    _applyHistorySnapshot()
    historyVersion.value++
  }

  function _applyHistorySnapshot() {
    if (!workflow.value) return
    const snapshot = JSON.parse(historyStack.value[historyIndex.value]!)
    workflow.value.nodes = snapshot.nodes
    workflow.value.edges = snapshot.edges
    workflow.value.name = snapshot.name
    checkDirty()
    selectNodes(null)
  }

  const canUndo = computed(() => historyIndex.value > 0)
  const canRedo = computed(() => historyIndex.value < historyStack.value.length - 1)

  const nodes = computed(() => workflow.value?.nodes ?? [])
  const edges = computed(() => workflow.value?.edges ?? [])

  // 兼容字段：取第一个选中节点 ID
  const selectedNodeId = computed<string | null>(
    () => selectedNodeIds.value[0] ?? null,
  )

  // 仅在单选时返回节点，多选或无选时返回 null
  const selectedNode = computed<WorkflowNode | null>(() => {
    if (!workflow.value) return null
    if (selectedNodeIds.value.length !== 1) return null
    const id = selectedNodeIds.value[0]
    return workflow.value.nodes.find((n) => n.id === id) ?? null
  })

  function selectNodes(ids: string[] | null) {
    selectedNodeIds.value = ids && ids.length ? [...ids] : []
  }

  // 向后兼容：单节点选择
  function selectNode(nodeId: string | null) {
    selectNodes(nodeId ? [nodeId] : null)
  }

  function setWorkflow(def: WorkflowDefinition) {
    workflow.value = def
    nodeRuntime.value = {}
    activeRunId.value = null
    selectedNodeIds.value = []
    isDirty.value = false
    lastSavedSnapshot = JSON.stringify({
      nodes: def.nodes,
      edges: def.edges,
      name: def.name,
    })
    historyStack.value = [lastSavedSnapshot]
    historyIndex.value = 0
    historyVersion.value = 0
  }

  function updateNodeConfig(nodeId: string, config: Record<string, unknown>) {
    if (!workflow.value) return
    const node = workflow.value.nodes.find((n) => n.id === nodeId)
    if (node) {
      node.config = { ...node.config, ...config }
      isDirty.value = true
    }
  }

  function setNodes(newNodes: WorkflowNode[]) {
    if (workflow.value) {
      workflow.value.nodes = newNodes
      isDirty.value = true
    }
  }

  function setEdges(newEdges: WorkflowEdge[]) {
    if (workflow.value) {
      workflow.value.edges = newEdges
      isDirty.value = true
    }
  }

  function setNodeStatus(nodeId: string, status: NodeStatus) {
    nodeRuntime.value[nodeId] = { ...(nodeRuntime.value[nodeId] ?? {}), status }
  }

  function setNodeRuntime(nodeId: string, info: Partial<NodeRuntimeInfo>) {
    nodeRuntime.value[nodeId] = { ...(nodeRuntime.value[nodeId] ?? { status: 'idle' }), ...info }
  }

  function resetRuntime() {
    nodeRuntime.value = {}
  }

  function setActiveRunId(runId: string | null) {
    activeRunId.value = runId
  }

  function markDirty() {
    isDirty.value = true
  }

  function markClean() {
    isDirty.value = false
    if (workflow.value) {
      lastSavedSnapshot = JSON.stringify({
        nodes: workflow.value.nodes,
        edges: workflow.value.edges,
        name: workflow.value.name,
      })
    }
  }

  function checkDirty() {
    if (!workflow.value) {
      isDirty.value = false
      return
    }
    const current = JSON.stringify({
      nodes: workflow.value.nodes,
      edges: workflow.value.edges,
      name: workflow.value.name,
    })
    isDirty.value = current !== lastSavedSnapshot
  }

  return {
    workflow,
    nodes,
    edges,
    selectedNodeIds,
    selectedNodeId,
    selectedNode,
    nodeRuntime,
    activeRunId,
    selectNodes,
    selectNode,
    setWorkflow,
    updateNodeConfig,
    setNodes,
    setEdges,
    setNodeStatus,
    setNodeRuntime,
    resetRuntime,
    setActiveRunId,
    markDirty,
    markClean,
    checkDirty,
    isDirty,
    // 撤销 / 重做
    historyVersion,
    commitHistory,
    undo,
    redo,
    canUndo,
    canRedo,
  }
})
