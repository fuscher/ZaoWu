<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Renderer, Program, Mesh, Triangle } from 'ogl'

const props = defineProps<{
  rotation?: number
  speed?: number
  colors?: string[]
  transparent?: boolean
  autoRotate?: number
  scale?: number
  frequency?: number
  warpStrength?: number
  mouseInfluence?: number
  parallax?: number
  noise?: number
  iterations?: number
  intensity?: number
  bandWidth?: number
}>()

const container = ref<HTMLDivElement>()

const vertexShader = `
attribute vec2 uv;
attribute vec2 position;
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position, 0, 1);
}
`

const fragmentShader = `
precision highp float;

#define MAX_COLORS 8

varying vec2 vUv;

uniform vec2 uCanvas;
uniform float uTime;
uniform float uSpeed;
uniform vec2 uRot;
uniform int uColorCount;
uniform vec3 uColors[8];
uniform int uTransparent;
uniform float uScale;
uniform float uFrequency;
uniform float uWarpStrength;
uniform vec2 uPointer;
uniform float uMouseInfluence;
uniform float uParallax;
uniform float uNoise;
uniform int uIterations;
uniform float uIntensity;
uniform float uBandWidth;

void main() {
  float t = uTime * uSpeed;
  vec2 p = vUv * 2.0 - 1.0;
  p += uPointer * uParallax * 0.1;
  vec2 rp = vec2(p.x * uRot.x - p.y * uRot.y, p.x * uRot.y + p.y * uRot.x);
  vec2 q = vec2(rp.x * (uCanvas.x / uCanvas.y), rp.y);
  q /= max(uScale, 0.0001);
  q /= 0.5 + 0.2 * dot(q, q);
  q += 0.2 * cos(t) - 7.56;
  vec2 toward = (uPointer - rp);
  q += toward * uMouseInfluence * 0.2;

  for (int j = 0; j < 5; j++) {
    if (j >= uIterations - 1) break;
    vec2 rr = sin(1.5 * (q.yx * uFrequency) + 2.0 * cos(q * uFrequency));
    q += (rr - q) * 0.15;
  }

  vec3 col = vec3(0.0);
  float a = 1.0;

  if (uColorCount > 0) {
    vec2 s = q;
    vec3 sumCol = vec3(0.0);
    float cover = 0.0;
    for (int i = 0; i < MAX_COLORS; ++i) {
      if (i >= uColorCount) break;
      s -= 0.01;
      vec2 r = sin(1.5 * (s.yx * uFrequency) + 2.0 * cos(s * uFrequency));
      float m0 = length(r + sin(5.0 * r.y * uFrequency - 3.0 * t + float(i)) / 4.0);
      float kBelow = clamp(uWarpStrength, 0.0, 1.0);
      float kMix = pow(kBelow, 0.3);
      float gain = 1.0 + max(uWarpStrength - 1.0, 0.0);
      vec2 disp = (r - s) * kBelow;
      vec2 warped = s + disp * gain;
      float m1 = length(warped + sin(5.0 * warped.y * uFrequency - 3.0 * t + float(i)) / 4.0);
      float m = mix(m0, m1, kMix);
      float w = 1.0 - exp(-uBandWidth / exp(uBandWidth * m));
      sumCol += uColors[i] * w;
      cover = max(cover, w);
    }
    col = clamp(sumCol, 0.0, 1.0);
    a = uTransparent > 0 ? cover : 1.0;
  } else {
    vec2 s = q;
    for (int k = 0; k < 3; ++k) {
      s -= 0.01;
      vec2 r = sin(1.5 * (s.yx * uFrequency) + 2.0 * cos(s * uFrequency));
      float m0 = length(r + sin(5.0 * r.y * uFrequency - 3.0 * t + float(k)) / 4.0);
      float kBelow = clamp(uWarpStrength, 0.0, 1.0);
      float kMix = pow(kBelow, 0.3);
      float gain = 1.0 + max(uWarpStrength - 1.0, 0.0);
      vec2 disp = (r - s) * kBelow;
      vec2 warped = s + disp * gain;
      float m1 = length(warped + sin(5.0 * warped.y * uFrequency - 3.0 * t + float(k)) / 4.0);
      float m = mix(m0, m1, kMix);
      col[k] = 1.0 - exp(-uBandWidth / exp(uBandWidth * m));
    }
    a = uTransparent > 0 ? max(max(col.r, col.g), col.b) : 1.0;
  }

  col *= uIntensity;

  if (uNoise > 0.0001) {
    float n = fract(sin(dot(gl_FragCoord.xy + vec2(uTime), vec2(12.9898, 78.233))) * 43758.5453123);
    col += (n - 0.5) * uNoise;
    col = clamp(col, 0.0, 1.0);
  }

  vec3 rgb = (uTransparent > 0) ? col * a : col;
  gl_FragColor = vec4(rgb, a);
}
`

function hexToVec3(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16) / 255,
    parseInt(h.slice(2, 4), 16) / 255,
    parseInt(h.slice(4, 6), 16) / 255,
  ]
}

function getActiveColors(): string[] {
  return (props.colors || []).filter(Boolean).slice(0, 8)
}

function buildColorUniforms() {
  const activeColors = getActiveColors()
  const uColors = Array.from({ length: 8 }, (_, i) => ({
    value: i < activeColors.length ? hexToVec3(activeColors[i]!) : ([0, 0, 0] as [number, number, number]),
  }))
  return {
    uColorCount: { value: activeColors.length },
    uColors,
  }
}

let renderer: Renderer | null = null
let program: Program | null = null
let mesh: Mesh | null = null
let animationId = 0
let gl: any = null
let currentPointer: [number, number] = [0, 0]
let targetPointer: [number, number] = [0, 0]

function init() {
  if (!container.value) return

  renderer = new Renderer({ alpha: true, premultipliedAlpha: false })
  gl = renderer.gl
  gl.clearColor(0, 0, 0, 0)

  const geometry = new Triangle(gl)
  const rotationRad = ((props.rotation ?? 90) * Math.PI) / 180

  program = new Program(gl, {
    vertex: vertexShader,
    fragment: fragmentShader,
    uniforms: {
      uCanvas: { value: [gl.canvas.width, gl.canvas.height] },
      uTime: { value: 0 },
      uSpeed: { value: props.speed ?? 0.2 },
      uRot: { value: [Math.cos(rotationRad), Math.sin(rotationRad)] },
      ...buildColorUniforms(),
      uTransparent: { value: (props.transparent ?? true) ? 1 : 0 },
      uScale: { value: props.scale ?? 1 },
      uFrequency: { value: props.frequency ?? 1 },
      uWarpStrength: { value: props.warpStrength ?? 1 },
      uPointer: { value: [0, 0] },
      uMouseInfluence: { value: props.mouseInfluence ?? 1 },
      uParallax: { value: props.parallax ?? 0.5 },
      uNoise: { value: props.noise ?? 0.15 },
      uIterations: { value: props.iterations ?? 1 },
      uIntensity: { value: props.intensity ?? 1.5 },
      uBandWidth: { value: props.bandWidth ?? 6 },
    },
  })

  mesh = new Mesh(gl, { geometry, program })
  container.value.appendChild(gl.canvas as HTMLCanvasElement)

  const autoRotateVal = props.autoRotate ?? 0

  function handlePointerMove(e: PointerEvent) {
    const rect = gl.canvas.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / (rect.width || 1)) * 2 - 1
    const y = -(((e.clientY - rect.top) / (rect.height || 1)) * 2 - 1)
    targetPointer = [x, y]
  }

  function handlePointerLeave() {
    targetPointer = [0, 0]
  }

  function resize() {
    if (!container.value || !renderer || !program) return
    const w = container.value.offsetWidth
    const h = container.value.offsetHeight
    if (w === 0 || h === 0) return
    renderer.setSize(w, h)
    program.uniforms.uCanvas.value = [w, h]
  }

  window.addEventListener('resize', resize)
  resize()

  gl.canvas.addEventListener('pointermove', handlePointerMove)
  gl.canvas.addEventListener('pointerleave', handlePointerLeave)

  function update(time: number) {
    animationId = requestAnimationFrame(update)
    if (!program) return

    const t = time * 0.001
    program.uniforms.uTime.value = t

    const deg = (props.rotation ?? 90) + autoRotateVal * t
    const rad = (deg * Math.PI) / 180
    program.uniforms.uRot.value = [Math.cos(rad), Math.sin(rad)]

    currentPointer[0] += 0.08 * (targetPointer[0] - currentPointer[0])
    currentPointer[1] += 0.08 * (targetPointer[1] - currentPointer[1])
    program.uniforms.uPointer.value = currentPointer

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
  currentPointer = [0, 0]
  targetPointer = [0, 0]
}

onMounted(() => { init() })
onUnmounted(() => { cleanup() })

watch(
  () => [
    props.speed,
    props.scale,
    props.frequency,
    props.warpStrength,
    props.mouseInfluence,
    props.parallax,
    props.noise,
    props.iterations,
    props.intensity,
    props.bandWidth,
    props.rotation,
    props.autoRotate,
    props.transparent,
    props.colors,
  ] as const,
  () => {
    cleanup()
    init()
  },
  { deep: false }
)
</script>

<script lang="ts">
export const bgMeta = {
  id: 'bends',
  name: 'Bends',
  defaultParams: {
    rotation: 90,
    speed: 0.2,
    colors: ['#0a4b5c', '#07839a', '#06B6D4', '#5dd4e8', '#b0ecf5'],
    transparent: true,
    autoRotate: 0,
    scale: 1,
    frequency: 1,
    warpStrength: 1,
    mouseInfluence: 1,
    parallax: 0.5,
    noise: 0.15,
    iterations: 1,
    intensity: 1.5,
    bandWidth: 6,
  },
}
</script>

<template>
  <div ref="container" class="bends-bg" />
</template>

<style scoped>
.bends-bg {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  -webkit-app-region: no-drag;
}
.bends-bg canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>