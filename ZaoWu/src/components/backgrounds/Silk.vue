<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Renderer, Program, Mesh, Triangle } from 'ogl'

const props = defineProps<{
  speed?: number
  scale?: number
  color?: string
  noiseIntensity?: number
  rotation?: number
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

varying vec2 vUv;

uniform float uTime;
uniform vec3  uColor;
uniform float uSpeed;
uniform float uScale;
uniform float uRotation;
uniform float uNoiseIntensity;

const float e = 2.71828182845904523536;

float noise(vec2 texCoord) {
  float G = e;
  vec2  r = (G * sin(G * texCoord));
  return fract(r.x * r.y * (1.0 + texCoord.x));
}

vec2 rotateUvs(vec2 uv, float angle) {
  float c = cos(angle);
  float s = sin(angle);
  mat2  rot = mat2(c, -s, s, c);
  return rot * uv;
}

void main() {
  float rnd        = noise(gl_FragCoord.xy);
  vec2  uv         = rotateUvs(vUv * uScale, uRotation);
  vec2  tex        = uv * uScale;
  float tOffset    = uSpeed * uTime;

  tex.y += 0.03 * sin(8.0 * tex.x - tOffset);

  float pattern = 0.6 +
                  0.4 * sin(5.0 * (tex.x + tex.y +
                                   cos(3.0 * tex.x + 5.0 * tex.y) +
                                   0.02 * tOffset) +
                           sin(20.0 * (tex.x + tex.y - 0.1 * tOffset)));

  vec4 col = vec4(uColor, 1.0) * vec4(pattern) - rnd / 15.0 * uNoiseIntensity;
  col.a = 1.0;
  gl_FragColor = col;
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

function init() {
  if (!container.value) return

  renderer = new Renderer({ alpha: true, premultipliedAlpha: false })
  gl = renderer.gl
  gl.clearColor(0, 0, 0, 0)

  const geometry = new Triangle(gl)
  const colorVal = hexToVec3(props.color ?? '#7B7481')

  program = new Program(gl, {
    vertex: vertexShader,
    fragment: fragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uColor: { value: colorVal },
      uSpeed: { value: props.speed ?? 5 },
      uScale: { value: props.scale ?? 1 },
      uRotation: { value: props.rotation ?? 0 },
      uNoiseIntensity: { value: props.noiseIntensity ?? 1.5 },
    },
  })

  mesh = new Mesh(gl, { geometry, program })
  container.value.appendChild(gl.canvas as HTMLCanvasElement)

  function resize() {
    if (!container.value || !renderer) return
    const w = container.value.offsetWidth
    const h = container.value.offsetHeight
    if (w === 0 || h === 0) return
    renderer.setSize(w, h)
  }

  window.addEventListener('resize', resize)
  resize()

  function update(time: number) {
    animationId = requestAnimationFrame(update)
    if (!program) return
    program.uniforms.uTime.value = time * 0.001
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

onMounted(() => { init() })
onUnmounted(() => { cleanup() })
</script>

<script lang="ts">
export const bgMeta = {
  id: 'silk',
  name: 'Silk',
  defaultParams: {
    speed: 5,
    scale: 1,
    color: '#7B7481',
    noiseIntensity: 1.5,
    rotation: 0,
  },
}
</script>

<template>
  <div ref="container" class="silk-bg" />
</template>

<style scoped>
.silk-bg {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  -webkit-app-region: no-drag;
}
.silk-bg canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
