import { ref, computed } from 'vue'
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

  // ── 撤销 / 重做历史（快照式）──
  const HISTORY_LIMIT = 50
  const history = ref<{ nodes: WorkflowNode[]; edges: WorkflowEdge[] }[]>([])
  const historyIndex = ref(-1)
  // 仅在撤销/重做时自增，画布监听它来重新载入；提交快照不 bump，避免每次变更都重载画布
  const historyVersion = ref(0)
  const canUndo = computed(() => historyIndex.value > 0)
  const canRedo = computed(() => historyIndex.value < history.value.length - 1)

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
    resetHistory()
  }

  function updateNodeConfig(nodeId: string, config: Record<string, unknown>) {
    if (!workflow.value) return
    const node = workflow.value.nodes.find((n) => n.id === nodeId)
    if (node) {
      node.config = { ...node.config, ...config }
    }
  }

  function setNodes(newNodes: WorkflowNode[]) {
    if (workflow.value) {
      workflow.value.nodes = newNodes
    }
  }

  function setEdges(newEdges: WorkflowEdge[]) {
    if (workflow.value) {
      workflow.value.edges = newEdges
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

  // ── 历史快照 ──
  function snapshot(): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
    return {
      nodes: JSON.parse(JSON.stringify(workflow.value?.nodes ?? [])) as WorkflowNode[],
      edges: JSON.parse(JSON.stringify(workflow.value?.edges ?? [])) as WorkflowEdge[],
    }
  }

  function restoreHistory(snap: { nodes: WorkflowNode[]; edges: WorkflowEdge[] }) {
    if (!workflow.value) return
    workflow.value.nodes = JSON.parse(JSON.stringify(snap.nodes))
    workflow.value.edges = JSON.parse(JSON.stringify(snap.edges))
    selectedNodeIds.value = []
    historyVersion.value++
  }

  // 在一次有意义的变更“结算”后调用，记录新快照（截断 redo 分支）
  function commitHistory() {
    if (!workflow.value) return
    history.value = history.value.slice(0, historyIndex.value + 1)
    history.value.push(snapshot())
    if (history.value.length > HISTORY_LIMIT) history.value.shift()
    historyIndex.value = history.value.length - 1
  }

  function resetHistory() {
    history.value = workflow.value ? [snapshot()] : []
    historyIndex.value = history.value.length - 1
  }

  function undo() {
    if (historyIndex.value <= 0) return
    historyIndex.value--
    const snap = history.value[historyIndex.value]
    if (snap) restoreHistory(snap)
  }

  function redo() {
    if (historyIndex.value >= history.value.length - 1) return
    historyIndex.value++
    const snap = history.value[historyIndex.value]
    if (snap) restoreHistory(snap)
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
    historyVersion,
    canUndo,
    canRedo,
    undo,
    redo,
    commitHistory,
    resetHistory,
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
  }
})
