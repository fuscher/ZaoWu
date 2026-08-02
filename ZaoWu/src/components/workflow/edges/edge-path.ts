/**
 * 工作流边路径生成工具
 *
 * 生成 ComfyUI 风格的平滑贝塞尔曲线：
 * - 源端口默认在节点右侧，目标端口在左侧
 * - 当源节点位于目标节点右侧时，控制点向两侧外扩形成 S 形绕弯，避免连线穿过节点
 * - 控制点水平偏移量随节点间距自适应，保证远近皆宜的曲线美感
 */

export interface EdgePathInput {
  sourceX: number
  sourceY: number
  targetX: number
  targetY: number
  sourcePosition?: 'left' | 'right' | 'top' | 'bottom'
  targetPosition?: 'left' | 'right' | 'top' | 'bottom'
}

export interface EdgePathResult {
  path: string
  centerX: number
  centerY: number
}

const MIN_CONTROL_OFFSET = 60

export function getComfyBezierPath(input: EdgePathInput): EdgePathResult {
  const {
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition = 'right',
    targetPosition = 'left',
  } = input

  const isHorizontal = sourcePosition === 'left' || sourcePosition === 'right'

  let c1x: number
  let c1y: number
  let c2x: number
  let c2y: number

  if (isHorizontal) {
    const dx = targetX - sourceX
    // 水平方向控制点偏移：取水平距离的一半，至少 MIN_CONTROL_OFFSET，
    // 这样当目标在源左侧时曲线会自然外扩形成绕弯
    const offset = Math.max(Math.abs(dx) * 0.5, MIN_CONTROL_OFFSET)
    c1x = sourcePosition === 'right' ? sourceX + offset : sourceX - offset
    c1y = sourceY
    c2x = targetPosition === 'left' ? targetX - offset : targetX + offset
    c2y = targetY
  } else {
    const dy = targetY - sourceY
    const offset = Math.max(Math.abs(dy) * 0.5, MIN_CONTROL_OFFSET)
    c1x = sourceX
    c1y = sourcePosition === 'bottom' ? sourceY + offset : sourceY - offset
    c2x = targetX
    c2y = targetPosition === 'top' ? targetY - offset : targetY + offset
  }

  const path = `M ${sourceX},${sourceY} C ${c1x},${c1y} ${c2x},${c2y} ${targetX},${targetY}`

  // 曲线中点（用于标签/脉冲定位）：三次贝塞尔在 t=0.5 处的坐标
  const t = 0.5
  const mt = 1 - t
  const centerX =
    mt * mt * mt * sourceX +
    3 * mt * mt * t * c1x +
    3 * mt * t * t * c2x +
    t * t * t * targetX
  const centerY =
    mt * mt * mt * sourceY +
    3 * mt * mt * t * c1y +
    3 * mt * t * t * c2y +
    t * t * t * targetY

  return { path, centerX, centerY }
}
