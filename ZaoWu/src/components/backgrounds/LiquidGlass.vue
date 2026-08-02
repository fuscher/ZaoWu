<script setup lang="ts">
/**
 * LiquidGlass — 流体玻璃/金属铬色背景特效（纯自动动画，无交互）
 *
 * 灵感来源：LiquidChrome (OGL React)
 * 核心技术：
 *   - 迭代 UV 位移（多层 sin/cos 波叠加，模拟流体扭曲）
 *   - 金属铬色公式（baseColor / abs(sin(time - uv.y - uv.x))）
 *   - 3×3 超级采样抗锯齿
 */
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Renderer, Program, Mesh, Triangle } from 'ogl'

const props = defineProps<{
  /** 基础颜色 (hex)，默认深蓝黑 */
  baseColor?: string
  /** 动画速度，默认 0.2 */
  speed?: number
  /** 波浪振幅，默认 0.5 */
  amplitude?: number
  /** X 轴频率，默认 3.0 */
  frequencyX?: number
  /** Y 轴频率，默认 2.0 */
  frequencyY?: number
}>()

const container = ref<HTMLDivElement>()

// ── Shaders ────────────────────────────────────────────────────

const vertexShader = /* glsl */ `
attribute vec2 uv;
attribute vec2 position;
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position, 0.0, 1.0);
}
`

const fragmentShader = /* glsl */ `
precision highp float;

uniform float uTime;
uniform vec3  uResolution;
uniform vec3  uBaseColor;
uniform float uAmplitude;
uniform float uFrequencyX;
uniform float uFrequencyY;

varying vec2 vUv;

// ── 核心渲染：单次采样 ──────────────────────────────────────────
vec4 renderImage(vec2 uvCoord) {
  vec2 fragCoord = uvCoord * uResolution.xy;
  vec2 uv = (2.0 * fragCoord - uResolution.xy) / min(uResolution.x, uResolution.y);

  // 迭代 UV 位移 — 多层 sin/cos 波叠加，产生流体扭曲
  for (float i = 1.0; i < 10.0; i++) {
    uv.x += uAmplitude / i * cos(i * uFrequencyX * uv.y + uTime);
    uv.y += uAmplitude / i * cos(i * uFrequencyY * uv.x + uTime);
  }

  // 金属铬色：用 sin 制造明暗交替的镜面反射感
  vec3 color = uBaseColor / abs(sin(uTime - uv.y - uv.x));
  return vec4(color, 1.0);
}

// ── 主入口：3×3 超级采样抗锯齿 ──────────────────────────────────
void main() {
  vec4 col = vec4(0.0);
  int  samples = 0;

  for (int i = -1; i <= 1; i++) {
    for (int j = -1; j <= 1; j++) {
      vec2 offset = vec2(float(i), float(j)) * (1.0 / min(uResolution.x, uResolution.y));
      col += renderImage(vUv + offset);
      samples++;
    }
  }

  gl_FragColor = col / float(samples);
}
`

// ── 工具函数 ────────────────────────────────────────────────────

function hexToVec3(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  if (h.length < 6) return [0.06, 0.06, 0.1]
  return [
    parseInt(h.slice(0, 2), 16) / 255,
    parseInt(h.slice(2, 4), 16) / 255,
    parseInt(h.slice(4, 6), 16) / 255,
  ]
}

// ── WebGL 状态 ──────────────────────────────────────────────────

let renderer: Renderer | null = null
let program: Program | null = null
let mesh: Mesh | null = null
let animationId = 0
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let gl: any = null

function init() {
  if (!container.value) return

  renderer = new Renderer({ alpha: true, premultipliedAlpha: false })
  gl = renderer.gl
  gl.clearColor(0, 0, 0, 0)

  const geometry = new Triangle(gl)

  program = new Program(gl, {
    vertex: vertexShader,
    fragment: fragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uResolution: {
        value: new Float32Array([gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height]),
      },
      uBaseColor: { value: new Float32Array(hexToVec3(props.baseColor ?? '#111122')) },
      uAmplitude: { value: props.amplitude ?? 0.5 },
      uFrequencyX: { value: props.frequencyX ?? 3.0 },
      uFrequencyY: { value: props.frequencyY ?? 2.0 },
    },
  })

  mesh = new Mesh(gl, { geometry, program })
  container.value.appendChild(gl.canvas as HTMLCanvasElement)

  function resize() {
    if (!container.value || !renderer || !program) return
    const w = container.value.offsetWidth
    const h = container.value.offsetHeight
    if (w === 0 || h === 0) return
    renderer.setSize(w, h)
    const res = program.uniforms.uResolution.value as Float32Array
    res[0] = w
    res[1] = h
    res[2] = w / h
  }

  window.addEventListener('resize', resize)
  resize()

  // ── 渲染循环 ──

  function update(time: number) {
    animationId = requestAnimationFrame(update)
    if (!program) return

    program.uniforms.uTime.value = time * 0.001 * (props.speed ?? 0.2)

    if (renderer && mesh) {
      renderer.render({ scene: mesh })
    }
  }

  animationId = requestAnimationFrame(update)
}

function cleanup() {
  if (animationId) cancelAnimationFrame(animationId)
  if (renderer && gl) {
    gl.getExtension('WEBGL_lose_context')?.loseContext()
  }
  renderer = null
  program = null
  mesh = null
  gl = null
}

onMounted(() => {
  init()
})

onUnmounted(() => {
  cleanup()
})

watch(
  () => [props.baseColor, props.speed, props.amplitude, props.frequencyX, props.frequencyY] as const,
  () => {
    cleanup()
    init()
  },
  { deep: false },
)
</script>

<script lang="ts">
export const bgMeta = {
  id: 'liquidglass',
  name: 'Liquid Glass',
  defaultParams: {
    baseColor: '#111122',
    speed: 0.2,
    amplitude: 0.5,
    frequencyX: 3.0,
    frequencyY: 2.0,
  },
}
</script>

<template>
  <div ref="container" class="liquid-glass-bg" />
</template>

<style scoped>
.liquid-glass-bg {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  -webkit-app-region: no-drag;
}

.liquid-glass-bg canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
