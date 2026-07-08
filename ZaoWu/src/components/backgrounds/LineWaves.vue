<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Renderer, Program, Mesh, Triangle } from 'ogl'
import type { BackgroundSettings } from '@/types'

const props = defineProps<{
  speed?: number
  innerLineCount?: number
  outerLineCount?: number
  warpIntensity?: number
  rotation?: number
  edgeFadeWidth?: number
  colorCycleSpeed?: number
  brightness?: number
  color1?: string
  color2?: string
  color3?: string
  enableMouseInteraction?: boolean
  mouseInfluence?: number
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

uniform float uTime;
uniform vec3 uResolution;
uniform float uSpeed;
uniform float uInnerLines;
uniform float uOuterLines;
uniform float uWarpIntensity;
uniform float uRotation;
uniform float uEdgeFadeWidth;
uniform float uColorCycleSpeed;
uniform float uBrightness;
uniform vec3 uColor1;
uniform vec3 uColor2;
uniform vec3 uColor3;
uniform vec2 uMouse;
uniform float uMouseInfluence;
uniform bool uEnableMouse;

#define HALF_PI 1.5707963

float hashF(float n) {
  return fract(sin(n * 127.1) * 43758.5453123);
}

float smoothNoise(float x) {
  float i = floor(x);
  float f = fract(x);
  float u = f * f * (3.0 - 2.0 * f);
  return mix(hashF(i), hashF(i + 1.0), u);
}

float displaceA(float coord, float t) {
  float result = sin(coord * 2.123) * 0.2;
  result += sin(coord * 3.234 + t * 4.345) * 0.1;
  result += sin(coord * 0.589 + t * 0.934) * 0.5;
  return result;
}

float displaceB(float coord, float t) {
  float result = sin(coord * 1.345) * 0.3;
  result += sin(coord * 2.734 + t * 3.345) * 0.2;
  result += sin(coord * 0.189 + t * 0.934) * 0.3;
  return result;
}

vec2 rotate2D(vec2 p, float angle) {
  float c = cos(angle);
  float s = sin(angle);
  return vec2(p.x * c - p.y * s, p.x * s + p.y * c);
}

void main() {
  vec2 coords = gl_FragCoord.xy / uResolution.xy;
  coords = coords * 2.0 - 1.0;
  coords = rotate2D(coords, uRotation);

  float halfT = uTime * uSpeed * 0.5;
  float fullT = uTime * uSpeed;

  float mouseWarp = 0.0;
  if (uEnableMouse) {
    vec2 mPos = rotate2D(uMouse * 2.0 - 1.0, uRotation);
    float mDist = length(coords - mPos);
    mouseWarp = uMouseInfluence * exp(-mDist * mDist * 4.0);
  }

  float warpAx = coords.x + displaceA(coords.y, halfT) * uWarpIntensity + mouseWarp;
  float warpAy = coords.y - displaceA(coords.x * cos(fullT) * 1.235, halfT) * uWarpIntensity;
  float warpBx = coords.x + displaceB(coords.y, halfT) * uWarpIntensity + mouseWarp;
  float warpBy = coords.y - displaceB(coords.x * sin(fullT) * 1.235, halfT) * uWarpIntensity;

  vec2 fieldA = vec2(warpAx, warpAy);
  vec2 fieldB = vec2(warpBx, warpBy);
  vec2 blended = mix(fieldA, fieldB, mix(fieldA, fieldB, 0.5));

  float fadeTop = smoothstep(uEdgeFadeWidth, uEdgeFadeWidth + 0.4, blended.y);
  float fadeBottom = smoothstep(-uEdgeFadeWidth, -(uEdgeFadeWidth + 0.4), blended.y);
  float vMask = 1.0 - max(fadeTop, fadeBottom);

  float tileCount = mix(uOuterLines, uInnerLines, vMask);
  float scaledY = blended.y * tileCount;
  float nY = smoothNoise(abs(scaledY));

  float ridge = pow(
    step(abs(nY - blended.x) * 2.0, HALF_PI) * cos(2.0 * (nY - blended.x)),
    5.0
  );

  float lines = 0.0;
  for (float i = 1.0; i < 3.0; i += 1.0) {
    lines += pow(max(fract(scaledY), fract(-scaledY)), i * 2.0);
  }

  float pattern = vMask * lines;

  float cycleT = fullT * uColorCycleSpeed;
  float rChannel = (pattern + lines * ridge) * (cos(blended.y + cycleT * 0.234) * 0.5 + 1.0);
  float gChannel = (pattern + vMask * ridge) * (sin(blended.x + cycleT * 1.745) * 0.5 + 1.0);
  float bChannel = (pattern + lines * ridge) * (cos(blended.x + cycleT * 0.534) * 0.5 + 1.0);

  vec3 col = (rChannel * uColor1 + gChannel * uColor2 + bChannel * uColor3) * uBrightness;
  float alpha = clamp(length(col), 0.0, 1.0);

  gl_FragColor = vec4(col, alpha);
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

let renderer: Renderer | null = null
let program: Program | null = null
let mesh: Mesh | null = null
let animationId = 0
let gl: any = null

function hexToVec3Uniforms(): Record<string, [number, number, number]> {
  return {
    uColor1: { value: hexToVec3(props.color1 ?? '#ffffff') },
    uColor2: { value: hexToVec3(props.color2 ?? '#ffffff') },
    uColor3: { value: hexToVec3(props.color3 ?? '#ffffff') },
  } as unknown as Record<string, [number, number, number]>
}

function init() {
  if (!container.value) return

  renderer = new Renderer({ alpha: true, premultipliedAlpha: false })
  gl = renderer.gl
  gl.clearColor(0, 0, 0, 0)

  const geometry = new Triangle(gl)
  const rotationRad = ((props.rotation ?? -45) * Math.PI) / 180

  program = new Program(gl, {
    vertex: vertexShader,
    fragment: fragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uResolution: {
        value: [gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height],
      },
      uSpeed: { value: props.speed ?? 0.3 },
      uInnerLines: { value: props.innerLineCount ?? 32 },
      uOuterLines: { value: props.outerLineCount ?? 36 },
      uWarpIntensity: { value: props.warpIntensity ?? 1.0 },
      uRotation: { value: rotationRad },
      uEdgeFadeWidth: { value: props.edgeFadeWidth ?? 0.0 },
      uColorCycleSpeed: { value: props.colorCycleSpeed ?? 1.0 },
      uBrightness: { value: props.brightness ?? 0.2 },
      ...hexToVec3Uniforms(),
      uMouse: { value: new Float32Array([0.5, 0.5]) },
      uMouseInfluence: { value: props.mouseInfluence ?? 2.0 },
      uEnableMouse: { value: props.enableMouseInteraction ?? true },
    },
  })

  mesh = new Mesh(gl, { geometry, program })
  container.value.appendChild(gl.canvas as HTMLCanvasElement)

  let currentMouse: [number, number] = [0.5, 0.5]
  let targetMouse: [number, number] = [0.5, 0.5]

  function handleMouseMove(e: MouseEvent) {
    const rect = gl.canvas.getBoundingClientRect()
    targetMouse = [
      (e.clientX - rect.left) / rect.width,
      1.0 - (e.clientY - rect.top) / rect.height,
    ]
  }

  function handleMouseLeave() {
    targetMouse = [0.5, 0.5]
  }

  function resize() {
    if (!container.value || !renderer || !program) return
    const w = container.value.offsetWidth
    const h = container.value.offsetHeight
    if (w === 0 || h === 0) return
    renderer.setSize(w, h)
    program.uniforms.uResolution.value = [w, h, w / h]
  }

  window.addEventListener('resize', resize)
  resize()

  if (props.enableMouseInteraction) {
    gl.canvas.addEventListener('mousemove', handleMouseMove)
    gl.canvas.addEventListener('mouseleave', handleMouseLeave)
  }

  function update(time: number) {
    animationId = requestAnimationFrame(update)
    if (!program) return

    program.uniforms.uTime.value = time * 0.001

    if (props.enableMouseInteraction) {
      currentMouse[0] += 0.05 * (targetMouse[0] - currentMouse[0])
      currentMouse[1] += 0.05 * (targetMouse[1] - currentMouse[1])
      ;(program.uniforms.uMouse.value as any)[0] = currentMouse[0]
      ;(program.uniforms.uMouse.value as any)[1] = currentMouse[1]
    }

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
  () => [props.speed, props.brightness, props.color1, props.color2, props.color3] as const,
  () => {
    cleanup()
    init()
  },
  { deep: false }
)
</script>

<script lang="ts">
export const bgMeta = {
  id: 'linewaves',
  name: 'Line Waves',
  defaultParams: {
    speed: 0.3,
    innerLineCount: 32,
    outerLineCount: 36,
    warpIntensity: 1.0,
    rotation: -45,
    edgeFadeWidth: 0.0,
    colorCycleSpeed: 1.0,
    brightness: 0.2,
    color1: '#ffffff',
    color2: '#ffffff',
    color3: '#ffffff',
    enableMouseInteraction: true,
    mouseInfluence: 2.0,
  },
}
</script>

<template>
  <div ref="container" class="line-waves-bg" />
</template>

<style scoped>
.line-waves-bg {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  -webkit-app-region: no-drag;
}

.line-waves-bg canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
