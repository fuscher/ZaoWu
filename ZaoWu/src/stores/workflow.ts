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
  const selectedNodeId = ref<string | null>(null)
  const nodeRuntime = ref<Record<string, NodeRuntimeInfo>>({})
  const activeRunId = ref<string | null>(null)

  const nodes = computed(() => workflow.value?.nodes ?? [])
  const edges = computed(() => workflow.value?.edges ?? [])

  const selectedNode = computed<WorkflowNode | null>(() => {
    if (!selectedNodeId.value || !workflow.value) return null
    return workflow.value.nodes.find(n => n.id === selectedNodeId.value) ?? null
  })

  function selectNode(nodeId: string | null) {
    selectedNodeId.value = nodeId
  }

  function setWorkflow(def: WorkflowDefinition) {
    workflow.value = def
    nodeRuntime.value = {}
    activeRunId.value = null
  }

  function updateNodeConfig(nodeId: string, config: Record<string, unknown>) {
    if (!workflow.value) return
    const node = workflow.value.nodes.find(n => n.id === nodeId)
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

  return {
    workflow,
    nodes,
    edges,
    selectedNodeId,
    selectedNode,
    nodeRuntime,
    activeRunId,
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
