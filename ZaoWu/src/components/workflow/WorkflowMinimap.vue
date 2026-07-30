<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import { Map as MapIcon, ChevronDown } from '@lucide/vue'
import { useI18n } from '@/i18n'

const { t } = useI18n()
// 小地图与父画布共享同一个 Vue Flow 实例（被置于 <VueFlow> 默认插槽内，
// 因此可直接拿到注入的 store，实时感知节点 / 视口 / 容器尺寸变化）
const { getNodes, getEdges, viewport, dimensions, setViewport } = useVueFlow()

// ── 小地图尺寸（CSS 像素，ComfyUI 风格右下角卡片） ──
const MINI_W = 210
const MINI_H = 150
const PAD = 10

// 节点类型配色：与画布语义一致，深浅主题下均清晰可辨
const NODE_COLORS: Record<string, string> = {
  start: '#22c55e',
  llm: '#3b82f6',
  condition: '#f59e0b',
  tool: '#a855f7',
  loop: '#ec4899',
  end: '#06b6d4',
}

// ── 显隐状态：默认开启，并记忆用户偏好 ──
const STORAGE_KEY = 'zaowu.workflow.minimap.visible'
const visible = ref(true)

function loadPref() {
  const saved = localStorage.getItem(STORAGE_KEY)
  // 未设置时默认开启
  visible.value = saved !== '0'
}

function toggle() {
  visible.value = !visible.value
  localStorage.setItem(STORAGE_KEY, visible.value ? '1' : '0')
}

function onKeyDown(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null
  const inEditable = !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
  if (inEditable) return
  // Ctrl/Cmd + M 快速切换小地图
  if ((e.ctrlKey || e.metaKey) && (e.key === 'm' || e.key === 'M')) {
    e.preventDefault()
    toggle()
  }
}

onMounted(() => {
  loadPref()
  window.addEventListener('keydown', onKeyDown)
})
onUnmounted(() => window.removeEventListener('keydown', onKeyDown))

// ── 计算所有节点的包围盒（flow 坐标系，留出边距） ──
const bounds = computed(() => {
  const nodes = getNodes.value as any[]
  if (!nodes.length) return null
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const n of nodes) {
    const w = n.dimensions?.width || 180
    const h = n.dimensions?.height || 80
    minX = Math.min(minX, n.position.x)
    minY = Math.min(minY, n.position.y)
    maxX = Math.max(maxX, n.position.x + w)
    maxY = Math.max(maxY, n.position.y + h)
  }
  const margin = 80
  return {
    minX: minX - margin,
    minY: minY - margin,
    maxX: maxX + margin,
    maxY: maxY + margin,
    w: maxX - minX + margin * 2,
    h: maxY - minY + margin * 2,
  }
})

// 缩放与居中偏移，把整张图塞进小地图并保持比例
const transform = computed(() => {
  const b = bounds.value
  if (!b) return null
  const innerW = MINI_W - PAD * 2
  const innerH = MINI_H - PAD * 2
  const scale = Math.min(innerW / Math.max(b.w, 1), innerH / Math.max(b.h, 1))
  const usedW = b.w * scale
  const usedH = b.h * scale
  const offsetX = PAD + (innerW - usedW) / 2
  const offsetY = PAD + (innerH - usedH) / 2
  return { scale, offsetX, offsetY, b }
})

const miniNodes = computed(() => {
  const tf = transform.value
  if (!tf) return []
  const nodes = getNodes.value as any[]
  return nodes.map((n) => {
    const w = n.dimensions?.width || 180
    const h = n.dimensions?.height || 80
    return {
      id: n.id,
      x: tf.offsetX + (n.position.x - tf.b.minX) * tf.scale,
      y: tf.offsetY + (n.position.y - tf.b.minY) * tf.scale,
      w: Math.max(2, w * tf.scale),
      h: Math.max(2, h * tf.scale),
      color: NODE_COLORS[n.type as string] || 'var(--accent)',
    }
  })
})

const miniEdges = computed(() => {
  const tf = transform.value
  if (!tf) return []
  const nodes = getNodes.value as any[]
  const posById = new Map<string, { x: number; y: number; w: number; h: number }>()
  for (const n of nodes) {
    const w = n.dimensions?.width || 180
    const h = n.dimensions?.height || 80
    posById.set(n.id, { x: n.position.x, y: n.position.y, w, h })
  }
  const edges = getEdges.value as any[]
  const out: { x1: number; y1: number; x2: number; y2: number; cond: boolean }[] = []
  for (const e of edges) {
    const s = posById.get(e.source)
    const tg = posById.get(e.target)
    if (!s || !tg) continue
    out.push({
      x1: tf.offsetX + (s.x + s.w / 2 - tf.b.minX) * tf.scale,
      y1: tf.offsetY + (s.y + s.h / 2 - tf.b.minY) * tf.scale,
      x2: tf.offsetX + (tg.x + tg.w / 2 - tf.b.minX) * tf.scale,
      y2: tf.offsetY + (tg.y + tg.h / 2 - tf.b.minY) * tf.scale,
      cond: e.edgeType === 'condition',
    })
  }
  return out
})

// 当前视口矩形（主画布可见区域映射到小地图坐标）
const viewportRect = computed(() => {
  const tf = transform.value
  if (!tf) return null
  const vp = viewport.value
  const dims = dimensions.value
  const zoom = vp.zoom || 1
  const w = (dims?.width || 800) / zoom
  const h = (dims?.height || 600) / zoom
  const x = -vp.x / zoom
  const y = -vp.y / zoom
  return {
    x: tf.offsetX + (x - tf.b.minX) * tf.scale,
    y: tf.offsetY + (y - tf.b.minY) * tf.scale,
    w: Math.max(4, w * tf.scale),
    h: Math.max(4, h * tf.scale),
  }
})

const zoomPercent = computed(() => Math.round((viewport.value?.zoom || 1) * 100))

// ── 拖拽 / 点击导航 ──
const svgRef = ref<SVGSVGElement | null>(null)
const dragging = ref(false)

function pointToFlow(clientX: number, clientY: number) {
  const tf = transform.value
  const svg = svgRef.value
  if (!tf || !svg) return null
  const rect = svg.getBoundingClientRect()
  const mx = clientX - rect.left
  const my = clientY - rect.top
  return {
    flowX: tf.b.minX + (mx - tf.offsetX) / tf.scale,
    flowY: tf.b.minY + (my - tf.offsetY) / tf.scale,
  }
}

function navigateTo(clientX: number, clientY: number) {
  const p = pointToFlow(clientX, clientY)
  if (!p) return
  const vp = viewport.value
  const dims = dimensions.value
  const zoom = vp.zoom || 1
  setViewport({
    x: (dims?.width || 800) / 2 - p.flowX * zoom,
    y: (dims?.height || 600) / 2 - p.flowY * zoom,
    zoom,
  })
}

function onPointerDown(e: PointerEvent) {
  dragging.value = true
  svgRef.value?.setPointerCapture(e.pointerId)
  navigateTo(e.clientX, e.clientY)
}
function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  navigateTo(e.clientX, e.clientY)
}
function onPointerUp(e: PointerEvent) {
  dragging.value = false
  svgRef.value?.releasePointerCapture(e.pointerId)
}
</script>

<template>
  <div class="workflow-minimap" :class="{ collapsed: !visible }" @pointerdown.stop @mousedown.stop>
    <!-- 收起后用于重新打开的悬浮按钮（右下角） -->
    <button
      v-if="!visible"
      class="minimap-fab"
      :title="t('workflow.minimap.show')"
      @click="toggle"
    >
      <MapIcon :size="16" />
    </button>

    <!-- 小地图面板 -->
    <div v-else class="minimap-panel">
      <div class="minimap-header">
        <span class="minimap-title">{{ t('workflow.minimap.title') }}</span>
        <span class="minimap-zoom">{{ zoomPercent }}%</span>
        <button
          class="minimap-collapse"
          :title="t('workflow.minimap.hide')"
          @click="toggle"
        >
          <ChevronDown :size="14" />
        </button>
      </div>
      <div class="minimap-body">
        <svg
          v-if="bounds"
          ref="svgRef"
          class="minimap-svg"
          :width="MINI_W"
          :height="MINI_H"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
        >
          <line
            v-for="(e, i) in miniEdges"
            :key="'e' + i"
            :x1="e.x1"
            :y1="e.y1"
            :x2="e.x2"
            :y2="e.y2"
            class="minimap-edge"
            :class="{ cond: e.cond }"
          />
          <rect
            v-for="n in miniNodes"
            :key="n.id"
            :x="n.x"
            :y="n.y"
            :width="n.w"
            :height="n.h"
            :fill="n.color"
            class="minimap-node"
            rx="2"
            ry="2"
          />
          <rect
            v-if="viewportRect"
            :x="viewportRect.x"
            :y="viewportRect.y"
            :width="viewportRect.w"
            :height="viewportRect.h"
            class="minimap-viewport"
          />
        </svg>
        <div v-else class="minimap-empty">{{ t('workflow.minimap.empty') }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workflow-minimap {
  position: absolute;
  right: 14px;
  bottom: 14px;
  z-index: 30;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  font-family: inherit;
  user-select: none;
}

.minimap-panel {
  width: 210px;
  background: var(--bg-glass);
  backdrop-filter: blur(12px) saturate(180%);
  -webkit-backdrop-filter: blur(12px) saturate(180%);
  border: 1px solid var(--border-glass);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.minimap-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
}

.minimap-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}

.minimap-zoom {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.minimap-collapse {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 5px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.minimap-collapse:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.minimap-body {
  position: relative;
}

.minimap-svg {
  display: block;
  cursor: crosshair;
  touch-action: none;
  background:
    radial-gradient(circle at 30% 20%, var(--accent-muted), transparent 70%),
    var(--bg-primary);
}

.minimap-edge {
  stroke: var(--border-hover);
  stroke-width: 1;
  opacity: 0.5;
}

.minimap-edge.cond {
  stroke: var(--warning);
  opacity: 0.7;
}

.minimap-node {
  opacity: 0.85;
  stroke: rgba(255, 255, 255, 0.25);
  stroke-width: 0.5;
}

.minimap-viewport {
  fill: var(--accent);
  fill-opacity: 0.12;
  stroke: var(--accent);
  stroke-width: 1.5;
}

.minimap-empty {
  padding: 24px 12px;
  text-align: center;
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--bg-primary);
}

.minimap-fab {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--bg-glass);
  backdrop-filter: blur(12px) saturate(180%);
  -webkit-backdrop-filter: blur(12px) saturate(180%);
  border: 1px solid var(--border-glass);
  color: var(--accent);
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: transform 0.15s ease, background 0.15s ease, color 0.15s ease;
}

.minimap-fab:hover {
  transform: scale(1.06);
  background: var(--bg-glass-hover);
  color: var(--accent-hover);
}
</style>
