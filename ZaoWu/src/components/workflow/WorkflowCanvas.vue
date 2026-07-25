<script setup lang="ts">
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import type { Connection, NodeDragEvent } from '@vue-flow/core'
import { computed, onMounted, onUnmounted } from 'vue'
import '@vue-flow/core/dist/style.css'
import StartNode from './nodes/StartNode.vue'
import LLMNode from './nodes/LLMNode.vue'
import ConditionNode from './nodes/ConditionNode.vue'
import ToolNode from './nodes/ToolNode.vue'
import EndNode from './nodes/EndNode.vue'
import LoopNode from './nodes/LoopNode.vue'
import RouterNode from './nodes/RouterNode.vue'
import DataFlowEdge from './edges/DataFlowEdge.vue'
import ConditionEdge from './edges/ConditionEdge.vue'
import BreakContinueEdge from './edges/BreakContinueEdge.vue'
import type { NodeType, EdgeType, WorkflowNode, WorkflowEdge } from '@/types/workflow'
import { useWorkflowStore } from '@/stores/workflow'

const nodeTypes = {
  start: StartNode,
  llm: LLMNode,
  condition: ConditionNode,
  tool: ToolNode,
  end: EndNode,
  loop: LoopNode,
  router: RouterNode,
}

const edgeTypes = {
  data: DataFlowEdge,
  condition: ConditionEdge,
  break: BreakContinueEdge,
  continue: BreakContinueEdge,
}

const workflowStore = useWorkflowStore()
const { onConnect, onNodeClick, onPaneClick, screenToFlowCoordinate } = useVueFlow()

const vueFlowNodes = computed(() =>
  workflowStore.nodes.map((n) => ({
    id: n.id,
    type: n.type,
    position: n.position,
    data: { label: n.label, config: n.config },
  }))
)

const vueFlowEdges = computed(() =>
  workflowStore.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourcePort,
    targetHandle: e.targetPort,
    type: e.type,
    edgeType: e.edgeType,
    animated: e.edgeType !== 'data',
    label: e.label,
  }))
)

onConnect((connection) => {
  if (!validateConnection(connection)) return
  const edgeType = inferEdgeKind(connection)
  const newEdge: WorkflowEdge = {
    id: `edge-${Date.now()}`,
    source: connection.source as string,
    sourcePort: connection.sourceHandle || 'default',
    target: connection.target as string,
    targetPort: connection.targetHandle || 'default',
    type: 'smoothstep',
    edgeType,
  }
  workflowStore.setEdges([...workflowStore.edges, newEdge])
})

onNodeClick(({ node }) => {
  workflowStore.selectNode(node.id)
})

onPaneClick(() => {
  workflowStore.selectNode(null)
})

function inferEdgeKind(connection: Connection): EdgeType {
  const sourcePort = connection.sourceHandle || 'default'
  const targetPort = connection.targetHandle || 'default'
  if (sourcePort === 'break' || sourcePort === 'continue') return sourcePort
  if (sourcePort === 'true' || sourcePort === 'false' || targetPort === 'true' || targetPort === 'false') {
    return 'condition'
  }
  return 'data'
}

function validateConnection(connection: Connection): boolean {
  if (!connection.source || !connection.target) return false
  if (connection.source === connection.target) return false
  if (wouldFormCycle(connection.source, connection.target)) return false

  const sourceHandle = connection.sourceHandle || 'default'
  if (sourceHandle === 'break' || sourceHandle === 'continue') {
    const sourceNode = vueFlowNodes.value.find((n) => n.id === connection.source)
    if (sourceNode && sourceNode.type !== 'loop') return false
  }

  return true
}

function wouldFormCycle(source: string, target: string): boolean {
  const adjacency = new Map<string, string[]>()
  for (const e of vueFlowEdges.value) {
    if (!adjacency.has(e.source)) adjacency.set(e.source, [])
    adjacency.get(e.source)!.push(e.target)
  }
  const visited = new Set<string>()
  const stack = [target]
  while (stack.length) {
    const cur = stack.pop()!
    if (cur === source) return true
    if (visited.has(cur)) continue
    visited.add(cur)
    for (const next of adjacency.get(cur) || []) {
      if (!visited.has(next)) stack.push(next)
    }
  }
  return false
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  const raw = event.dataTransfer?.getData('application/json')
  if (!raw) return
  const payload = JSON.parse(raw) as { type: NodeType; defaultData: Record<string, unknown> }
  const position = screenToFlowCoordinate({
    x: event.clientX,
    y: event.clientY,
  })
  const id = `node-${Date.now()}`
  const newNode: WorkflowNode = {
    id,
    type: payload.type,
    position,
    label: (payload.defaultData.label as string) || payload.type,
    config: (payload.defaultData.config as Record<string, unknown>) || {},
  }
  workflowStore.setNodes([...workflowStore.nodes, newNode])
}

function onNodeDragStop(event: NodeDragEvent) {
  const updated = workflowStore.nodes.map((n) => {
    if (n.id !== event.node.id) return n
    return { ...n, position: event.node.position }
  })
  workflowStore.setNodes(updated)
}

function deleteSelectedNode() {
  const nodeId = workflowStore.selectedNodeId
  if (!nodeId) return
  const newNodes = workflowStore.nodes.filter((n) => n.id !== nodeId)
  const newEdges = workflowStore.edges.filter(
    (e) => e.source !== nodeId && e.target !== nodeId,
  )
  workflowStore.setNodes(newNodes)
  workflowStore.setEdges(newEdges)
  workflowStore.selectNode(null)
}

function onKeyDown(event: KeyboardEvent) {
  if (event.key !== 'Delete' && event.key !== 'Backspace') return
  const target = event.target as HTMLElement
  if (
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.isContentEditable
  ) {
    return
  }
  deleteSelectedNode()
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
})
</script>

<template>
  <div class="workflow-canvas">
    <VueFlow
      :nodes="vueFlowNodes"
      :edges="vueFlowEdges"
      :node-types="nodeTypes"
      :edge-types="edgeTypes"
      :default-viewport="{ x: 0, y: 0, zoom: 1 }"
      :min-zoom="0.1"
      :max-zoom="2"
      :snap-to-grid="true"
      :snap-grid="[20, 20]"
      fit-view-on-init
      @node-drag-stop="onNodeDragStop"
      @dragover="onDragOver"
      @drop="onDrop"
    >
      <Background variant="lines" :gap="20" :line-width="1" color="var(--border-glass)" />
    </VueFlow>
  </div>
</template>

<style scoped>
.workflow-canvas {
  width: 100%;
  height: 100%;
}
</style>
