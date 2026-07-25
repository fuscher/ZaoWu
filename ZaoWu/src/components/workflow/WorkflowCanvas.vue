<script setup lang="ts">
import {
  VueFlow,
  useVueFlow,
  type Connection,
  type GraphNode,
  type GraphEdge,
  type NodeChange,
  type EdgeChange,
} from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
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
const {
  onConnect,
  onNodeClick,
  onPaneClick,
  screenToFlowCoordinate,
  getNodes,
  getViewport,
  getSelectedNodes,
  getSelectedEdges,
  fitView,
} = useVueFlow()

// ── 受控模式：v-model:nodes / v-model:edges 让 Vue Flow 自动双向同步 ──
// 画布内部状态使用 any[]：Vue Flow 的 GraphNode/GraphEdge 类型递归极深，
// 在 ref 与 .filter/.map 等操作中会触发 TS2589（类型实例化过深）。
// 节点/边的对象结构仍由 toVueFlowNode / toVueFlowEdge 在创建时保证。
const nodes = ref<any[]>([])
const edges = ref<any[]>([])

function toVueFlowNode(n: WorkflowNode): GraphNode {
  return {
    id: n.id,
    type: n.type,
    position: { x: n.position.x, y: n.position.y },
    data: { label: n.label, config: n.config },
  } as unknown as GraphNode
}

function toVueFlowEdge(e: WorkflowEdge): GraphEdge {
  return {
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourcePort,
    targetHandle: e.targetPort,
    type: e.type,
    // 自定义边组件读取的语义字段
    edgeType: e.edgeType,
    animated: e.edgeType !== 'data',
    label: e.label,
  } as unknown as GraphEdge
}

// 从 store 重新载入画布（用于新建 / 加载 / 导入工作流 / 撤销重做）
function loadFromStore(fit = true) {
  nodes.value = workflowStore.nodes.map(toVueFlowNode)
  edges.value = workflowStore.edges.map(toVueFlowEdge)
  workflowStore.selectNodes(null)
  if (!fit) return
  // 载入后自动适配视图（Vue Flow 可能尚未完成测量，失败可忽略）
  requestAnimationFrame(() => {
    try {
      fitView({ padding: 0.2 })
    } catch {
      /* Vue Flow 尚未就绪，忽略 */
    }
  })
}

onMounted(() => {
  loadFromStore()
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('mousemove', onWindowMouseMove)
  window.addEventListener('mouseup', onWindowMouseUp)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('mousemove', onWindowMouseMove)
  window.removeEventListener('mouseup', onWindowMouseUp)
})

// 工作流切换（新建 / 加载 / 导入 / 另存为）时重新载入画布
watch(
  () => workflowStore.workflow?.id,
  () => loadFromStore(),
)

// 撤销 / 重做：store 恢复快照后自增 historyVersion，画布据此重载（不重新 fitView）
watch(
  () => workflowStore.historyVersion,
  () => loadFromStore(false),
)

// ── 节点 / 边的变更回写 ──
function onNodesChange(changes: NodeChange[]) {
  let dragEnded = false
  for (const change of changes) {
    if (change.type === 'position') {
      if (change.position) syncStoreNodePosition(change.id, change.position)
      if (change.dragging === false) dragEnded = true
    } else if (change.type === 'remove') {
      syncStoreRemoveNode(change.id)
    }
  }
  if (dragEnded) {
    nextTick(() => workflowStore.commitHistory())
  }
  syncSelectionFromCanvas()
}

function onEdgesChange(changes: EdgeChange[]) {
  for (const change of changes) {
    if (change.type === 'remove') {
      syncStoreRemoveEdge(change.id)
    }
  }
}

function syncStoreNodePosition(id: string, position: { x: number; y: number }) {
  const def = workflowStore.workflow
  if (!def) return
  const node = def.nodes.find((n) => n.id === id)
  if (node) node.position = { x: position.x, y: position.y }
}

function syncStoreRemoveNode(id: string) {
  if (!workflowStore.workflow) return
  workflowStore.setNodes(workflowStore.nodes.filter((n) => n.id !== id))
  workflowStore.setEdges(
    workflowStore.edges.filter((e) => e.source !== id && e.target !== id),
  )
}

function syncStoreRemoveEdge(id: string) {
  if (!workflowStore.workflow) return
  workflowStore.setEdges(workflowStore.edges.filter((e) => e.id !== id))
}

// 把画布上的选择状态同步到 store（store 仅跟踪节点选择）
function syncSelectionFromCanvas() {
  const ids = getSelectedNodes.value.map((n) => n.id)
  workflowStore.selectNodes(ids)
}

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
  edges.value = [...edges.value, toVueFlowEdge(newEdge)]
  workflowStore.setEdges([...workflowStore.edges, newEdge])
  workflowStore.commitHistory()
})

onNodeClick(({ node }) => {
  workflowStore.selectNodes([node.id])
})

onPaneClick(() => {
  // 点击空白处：清空选择（与下方自定义框选互斥，单击不触发框选）
  workflowStore.selectNodes(null)
})

// ── 自定义框选：自己渲染矩形 + 自己按坐标计算命中，不依赖 Vue Flow 内置框选 ──
// 原因：项目里 Vue Flow 的 :selection-on-drag 矩形在历史版本中渲染不稳定，
// 手动实现可控、且能精确套用蓝色辉光高亮。
const canvasEl = ref<HTMLElement | null>(null)
const isSelecting = ref(false)
const selectionRect = ref<{ left: number; top: number; width: number; height: number } | null>(null)
let selectStart: { x: number; y: number } | null = null
let selectStartFlow: { x: number; y: number } | null = null
// didDrag：本次按下是否真的拖动过（区分“单击清空”与“框选”）
let didDrag = false
// justBoxSelected：刚完成一次真实框选，需拦截随后浏览器补发的 click
let justBoxSelected = false

function onCanvasMouseDown(event: MouseEvent) {
  // 仅左键 + 空白画布区域才启动框选；点节点/边/连接点交给 Vue Flow 处理
  if (event.button !== 0) return
  const target = event.target as HTMLElement
  if (target.closest('.vue-flow__node, .vue-flow__edge, .vue-flow__handle')) return
  const wrapper = canvasEl.value
  if (!wrapper) return
  const rect = wrapper.getBoundingClientRect()
  selectStart = { x: event.clientX, y: event.clientY }
  selectStartFlow = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  isSelecting.value = true
  didDrag = false
  selectionRect.value = {
    left: event.clientX - rect.left,
    top: event.clientY - rect.top,
    width: 0,
    height: 0,
  }
  event.preventDefault() // 避免拖拽时误选文本
}

function onWindowMouseMove(event: MouseEvent) {
  if (!isSelecting.value || !selectStart || !canvasEl.value) return
  const rect = canvasEl.value.getBoundingClientRect()
  const curX = event.clientX
  const curY = event.clientY
  if (Math.abs(curX - selectStart.x) > 3 || Math.abs(curY - selectStart.y) > 3) {
    didDrag = true
  }
  selectionRect.value = {
    left: Math.min(selectStart.x, curX) - rect.left,
    top: Math.min(selectStart.y, curY) - rect.top,
    width: Math.abs(curX - selectStart.x),
    height: Math.abs(curY - selectStart.y),
  }
}

function onWindowMouseUp(event: MouseEvent) {
  if (!isSelecting.value) return
  isSelecting.value = false
  const rect = selectionRect.value
  const startFlow = selectStartFlow
  selectionRect.value = null
  selectStart = null
  selectStartFlow = null

  if (!rect || !startFlow) return
  // 极小拖动视为单击：清空选择
  if (rect.width < 4 && rect.height < 4) {
    applySelection(new Set(), new Set())
    return
  }
  const endFlow = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  const minX = Math.min(startFlow.x, endFlow.x)
  const maxX = Math.max(startFlow.x, endFlow.x)
  const minY = Math.min(startFlow.y, endFlow.y)
  const maxY = Math.max(startFlow.y, endFlow.y)

  // 节点尺寸是在屏幕像素空间，需除以缩放才能得到 flow 坐标系下的尺寸
  const zoom = getViewport().zoom || 1
  const selectedNodeIds = new Set<string>()
  for (const gn of getNodes.value) {
    // 节点尺寸在屏幕像素空间，需除以缩放得到 flow 坐标系尺寸；
    // 若尚未测量（dimensions 为 0）则回退到默认尺寸，保证框选命中可靠
    const w = (gn.dimensions?.width || 180) / zoom
    const h = (gn.dimensions?.height || 80) / zoom
    const nx = gn.position.x
    const ny = gn.position.y
    // 矩形与节点包围盒相交即选中
    if (nx + w >= minX && nx <= maxX && ny + h >= minY && ny <= maxY) {
      selectedNodeIds.add(gn.id)
    }
  }

  // 两端节点中心都落在框内的连接线才选中
  const selectedEdgeIds = new Set<string>()
  for (const e of edges.value) {
    const s = getNodes.value.find((n) => n.id === e.source)
    const t = getNodes.value.find((n) => n.id === e.target)
    if (!s || !t) continue
    const sc = {
      x: s.position.x + ((s.dimensions?.width || 180) / zoom) / 2,
      y: s.position.y + ((s.dimensions?.height || 80) / zoom) / 2,
    }
    const tc = {
      x: t.position.x + ((t.dimensions?.width || 180) / zoom) / 2,
      y: t.position.y + ((t.dimensions?.height || 80) / zoom) / 2,
    }
    const inBox = (p: { x: number; y: number }) =>
      p.x >= minX && p.x <= maxX && p.y >= minY && p.y <= maxY
    if (inBox(sc) && inBox(tc)) selectedEdgeIds.add(e.id)
  }

  const isRealDrag = didDrag
  applySelection(selectedNodeIds, selectedEdgeIds)
  // 真实框选后浏览器会补发一次 click，Vue Flow 的 onPaneClick 会把刚框选的选择清空；
  // 标记后由 capture 阶段的点击拦截器保住辉光（参见 onCanvasClickCapture）
  if (isRealDrag) {
    justBoxSelected = true
    setTimeout(() => {
      justBoxSelected = false
    }, 0)
  }
}

// 将选中的节点/边写回受控数组并同步 store
function applySelection(nodeIds: Set<string>, edgeIds: Set<string>) {
  nodes.value = nodes.value.map((n) => ({ ...n, selected: nodeIds.has(n.id) }))
  edges.value = edges.value.map((e) => ({ ...e, selected: edgeIds.has(e.id) }))
  workflowStore.selectNodes(nodeIds.size ? [...nodeIds] : null)
}

// 真实框选在 mouseup 应用高亮后，浏览器会补发一次 click；
// 在 capture 阶段拦截它，阻止 Vue Flow 的 onPaneClick 清空刚框选的选择
function onCanvasClickCapture(event: MouseEvent) {
  if (justBoxSelected) {
    justBoxSelected = false
    event.stopPropagation()
    event.preventDefault()
  }
}

function inferEdgeKind(connection: Connection): EdgeType {
  const sourcePort = connection.sourceHandle || 'default'
  const targetPort = connection.targetHandle || 'default'
  if (sourcePort === 'break' || sourcePort === 'continue') return sourcePort
  if (
    sourcePort === 'true' ||
    sourcePort === 'false' ||
    targetPort === 'true' ||
    targetPort === 'false'
  ) {
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
  nodes.value = [...nodes.value, toVueFlowNode(newNode)]
  workflowStore.setNodes([...workflowStore.nodes, newNode])
  workflowStore.commitHistory()
}

// ============ 批量操作 ============
interface ClipboardData {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

const clipboard = ref<ClipboardData | null>(null)
const pasteCount = ref(0)
const lastMousePosition = ref<{ x: number; y: number } | null>(null)
const mouseOverCanvas = ref(false)

function genId(prefix: string, index: number): string {
  return `${prefix}-${Date.now()}-${index}-${Math.random().toString(36).slice(2, 8)}`
}

function getSelectedNodeIds(): string[] {
  return getSelectedNodes.value.map((n) => n.id)
}

function getSelectedEdgeIds(): string[] {
  return getSelectedEdges.value.map((e) => e.id)
}

function deleteSelectedItems() {
  const nodeIds = new Set(getSelectedNodeIds())
  const edgeIds = new Set(getSelectedEdgeIds())

  if (nodeIds.size === 0 && edgeIds.size === 0) return

  // 直接从画布本地状态删除选中节点，以及与选中节点相连的所有边
  nodes.value = nodes.value.filter((n) => !nodeIds.has(n.id))
  edges.value = edges.value.filter(
    (e) => !edgeIds.has(e.id) && !nodeIds.has(e.source) && !nodeIds.has(e.target),
  )

  // 同步回 store
  if (workflowStore.workflow) {
    workflowStore.setNodes(workflowStore.nodes.filter((n) => !nodeIds.has(n.id)))
    workflowStore.setEdges(
      workflowStore.edges.filter(
        (e) => !edgeIds.has(e.id) && !nodeIds.has(e.source) && !nodeIds.has(e.target),
      ),
    )
  }
  workflowStore.selectNodes(null)
  workflowStore.commitHistory()
}

function cloneWorkflowNode(node: WorkflowNode): WorkflowNode {
  return JSON.parse(JSON.stringify(node)) as WorkflowNode
}

function cloneWorkflowEdge(edge: WorkflowEdge): WorkflowEdge {
  return JSON.parse(JSON.stringify(edge)) as WorkflowEdge
}

function copySelectedItems() {
  const nodeIds = new Set(getSelectedNodeIds())
  if (nodeIds.size === 0) return

  const copiedNodes: WorkflowNode[] = []
  for (const n of workflowStore.nodes) {
    if (nodeIds.has(n.id)) {
      copiedNodes.push(cloneWorkflowNode(n))
    }
  }

  // 仅复制两端节点都在选中集合中的边
  const copiedEdges: WorkflowEdge[] = []
  for (const e of workflowStore.edges) {
    if (nodeIds.has(e.source) && nodeIds.has(e.target)) {
      copiedEdges.push(cloneWorkflowEdge(e))
    }
  }

  clipboard.value = { nodes: copiedNodes, edges: copiedEdges }
  pasteCount.value = 0
}

function pasteItems(mousePosition?: { x: number; y: number }) {
  if (!clipboard.value || clipboard.value.nodes.length === 0) return

  const oldToNew = new Map<string, string>()
  clipboard.value.nodes.forEach((node, index) => {
    oldToNew.set(node.id, genId('node', index))
  })

  // 计算原节点组中心点
  const minX = Math.min(...clipboard.value.nodes.map((n) => n.position.x))
  const maxX = Math.max(...clipboard.value.nodes.map((n) => n.position.x))
  const minY = Math.min(...clipboard.value.nodes.map((n) => n.position.y))
  const maxY = Math.max(...clipboard.value.nodes.map((n) => n.position.y))
  const oldCenter = { x: (minX + maxX) / 2, y: (minY + maxY) / 2 }

  let newCenter = { x: oldCenter.x, y: oldCenter.y }
  if (mousePosition && mouseOverCanvas.value) {
    const flowPos = screenToFlowCoordinate(mousePosition)
    newCenter = { x: flowPos.x, y: flowPos.y }
  } else {
    const offset = 40 * (pasteCount.value + 1)
    newCenter = { x: oldCenter.x + offset, y: oldCenter.y + offset }
  }

  const dx = newCenter.x - oldCenter.x
  const dy = newCenter.y - oldCenter.y

  const newNodes: WorkflowNode[] = []
  const newEdges: WorkflowEdge[] = []

  clipboard.value.nodes.forEach((node, index) => {
    const newId = oldToNew.get(node.id)!
    newNodes.push({
      ...cloneWorkflowNode(node),
      id: newId,
      position: {
        x: Math.round((node.position.x + dx) / 20) * 20,
        y: Math.round((node.position.y + dy) / 20) * 20,
      },
    })
  })

  clipboard.value.edges.forEach((edge, index) => {
    const newSource = oldToNew.get(edge.source)
    const newTarget = oldToNew.get(edge.target)
    if (!newSource || !newTarget) return
    newEdges.push({
      ...cloneWorkflowEdge(edge),
      id: genId('edge', index),
      source: newSource,
      target: newTarget,
    })
  })

  // 写入画布本地状态：取消旧选择，选中新粘贴节点
  nodes.value = [
    ...nodes.value.map((n) => ({ ...n, selected: false })),
    ...newNodes.map((n) => ({ ...toVueFlowNode(n), selected: true })),
  ]
  edges.value = [...edges.value, ...newEdges.map(toVueFlowEdge)]

  // 同步回 store
  if (workflowStore.workflow) {
    workflowStore.setNodes([...workflowStore.nodes, ...newNodes])
    workflowStore.setEdges([...workflowStore.edges, ...newEdges])
  }

  workflowStore.selectNodes(newNodes.map((n) => n.id))

  workflowStore.commitHistory()
  pasteCount.value++
}

// ============ 键盘事件 ============
function onKeyDown(event: KeyboardEvent) {
  const target = event.target as HTMLElement
  const inEditable =
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.isContentEditable
  if (inEditable) return

  const isMod = event.ctrlKey || event.metaKey

  if (event.key === 'Delete' || event.key === 'Backspace') {
    event.preventDefault()
    deleteSelectedItems()
    return
  }

  if (isMod && (event.key === 'c' || event.key === 'C')) {
    event.preventDefault()
    copySelectedItems()
    return
  }

  if (isMod && (event.key === 'v' || event.key === 'V')) {
    event.preventDefault()
    pasteItems(lastMousePosition.value ?? undefined)
    return
  }

  // 撤销 / 重做
  if (isMod && (event.key === 'z' || event.key === 'Z')) {
    event.preventDefault()
    if (event.shiftKey) workflowStore.redo()
    else workflowStore.undo()
    return
  }
  if (isMod && (event.key === 'y' || event.key === 'Y')) {
    event.preventDefault()
    workflowStore.redo()
    return
  }
}

function onCanvasMouseMove(event: MouseEvent) {
  lastMousePosition.value = { x: event.clientX, y: event.clientY }
  mouseOverCanvas.value = true
}

function onCanvasMouseLeave() {
  mouseOverCanvas.value = false
}

// 暴露给父组件（WorkflowPanel）调用的操作入口
defineExpose({
  copySelectedItems,
  pasteItems,
  deleteSelectedItems,
})
</script>

<template>
  <div
    class="workflow-canvas"
    ref="canvasEl"
    @mousedown="onCanvasMouseDown"
    @mousemove="onCanvasMouseMove"
    @mouseleave="onCanvasMouseLeave"
    @click.capture="onCanvasClickCapture"
  >
    <VueFlow
      v-model:nodes="nodes"
      v-model:edges="edges"
      :node-types="nodeTypes"
      :edge-types="edgeTypes"
      :default-viewport="{ x: 0, y: 0, zoom: 1 }"
      :min-zoom="0.1"
      :max-zoom="2"
      :snap-to-grid="true"
      :snap-grid="[20, 20]"
      :pan-on-drag="[2]"
      :delete-key-code="null"
      fit-view-on-init
      @nodes-change="onNodesChange"
      @edges-change="onEdgesChange"
      @dragover="onDragOver"
      @drop="onDrop"
      @contextmenu.prevent
    >
      <Background variant="lines" :gap="20" :line-width="1" color="var(--border-glass)" />
    </VueFlow>
    <div
      v-if="selectionRect"
      class="selection-rect"
      :style="{
        left: selectionRect.left + 'px',
        top: selectionRect.top + 'px',
        width: selectionRect.width + 'px',
        height: selectionRect.height + 'px',
      }"
    ></div>
  </div>
</template>

<style scoped>
.workflow-canvas {
  width: 100%;
  height: 100%;
  position: relative;
  /* 拖拽框选时避免误选中文本 */
  user-select: none;
}

/* 框选矩形：高透明蓝色遮罩 */
.selection-rect {
  position: absolute;
  z-index: 40;
  pointer-events: none;
  background: rgba(59, 130, 246, 0.10);
  border: 1px solid rgba(59, 130, 246, 0.85);
  border-radius: 3px;
}

/* 框选命中的节点：蓝色辉光高亮 */
:deep(.vue-flow__node.selected) {
  box-shadow:
    0 0 0 2px #3b82f6,
    0 0 16px 2px rgba(59, 130, 246, 0.55);
}

/* 框选命中的连接线：蓝色描边 + 辉光 */
:deep(.vue-flow__edge.selected) .vue-flow__edge-path {
  stroke: #3b82f6 !important;
  stroke-width: 2.5;
  filter: drop-shadow(0 0 6px rgba(59, 130, 246, 0.9));
}
</style>
