<script setup lang="ts">
import { VueFlow, useVueFlow, Position } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import type { Connection, NodeDragEvent } from '@vue-flow/core'
import { computed, watch } from 'vue'
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
const { nodes, edges, onConnect, addNodes, addEdges, onNodeClick, onPaneClick, screenToFlowCoordinate } = useVueFlow()

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

watch(vueFlowNodes, (val) => {
  nodes.value = val as any
}, { immediate: true })

watch(vueFlowEdges, (val) => {
  edges.value = val as any
}, { immediate: true })

onConnect((connection) => {
  if (!validateConnection(connection)) return
  const edge = {
    ...connection,
    id: `edge-${Date.now()}`,
    type: 'smoothstep',
    edgeType: inferEdgeKind(connection),
    animated: false,
  }
  addEdges([edge])

  const newEdge: WorkflowEdge = {
    id: edge.id,
    source: connection.source as string,
    sourcePort: connection.sourceHandle || 'default',
    target: connection.target as string,
    targetPort: connection.targetHandle || 'default',
    type: 'smoothstep',
    edgeType: edge.edgeType as EdgeType,
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
    const sourceNode = nodes.value.find((n) => n.id === connection.source)
    if (sourceNode && sourceNode.type !== 'loop') return false
  }

  return true
}

function wouldFormCycle(source: string, target: string): boolean {
  const adjacency = new Map<string, string[]>()
  for (const e of edges.value) {
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
  const raw = event.dataTransfer?.getData('application/json')
  if (!raw) return
  const payload = JSON.parse(raw) as { type: NodeType; defaultData: Record<string, unknown> }
  const position = screenToFlowCoordinate({
    x: event.clientX,
    y: event.clientY,
  })
  const id = `node-${Date.now()}`
  addNodes([{
    id,
    type: payload.type,
    position,
    data: payload.defaultData,
  }] as any)

  const newNode: WorkflowNode = {
    id,
    type: payload.type,
    position,
    label: (payload.defaultData.label as string) || payload.type,
    config: (payload.defaultData.config as Record<string, unknown>) || {},
  }
  workflowStore.setNodes([...workflowStore.nodes, newNode])
}

function onNodeDragStop(_event: NodeDragEvent) {
  const updated = workflowStore.nodes.map((n) => {
    const vfNode = nodes.value.find((vn) => vn.id === n.id)
    if (!vfNode) return n
    return { ...n, position: vfNode.position }
  })
  workflowStore.setNodes(updated)
}

defineExpose({ nodes, edges })
</script>

<template>
  <div class="workflow-canvas" @dragover="onDragOver" @drop="onDrop">
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :node-types="nodeTypes"
      :edge-types="edgeTypes"
      :default-viewport="{ x: 0, y: 0, zoom: 1 }"
      :min-zoom="0.1"
      :max-zoom="2"
      :snap-to-grid="true"
      :snap-grid="[20, 20]"
      fit-view-on-init
      @node-drag-stop="onNodeDragStop"
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
