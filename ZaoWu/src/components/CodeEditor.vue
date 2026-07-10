<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import { EditorView, keymap, lineNumbers, highlightActiveLineGutter, highlightSpecialChars, drawSelection } from '@codemirror/view'
import { EditorState, Compartment, Prec } from '@codemirror/state'
import { defaultKeymap, history } from '@codemirror/commands'
import { LanguageSupport, indentOnInput, bracketMatching } from '@codemirror/language'
import { closeBrackets } from '@codemirror/autocomplete'
import { oneDark } from '@codemirror/theme-one-dark'
import { json } from '@codemirror/lang-json'
import { javascript } from '@codemirror/lang-javascript'
import { html } from '@codemirror/lang-html'
import { css } from '@codemirror/lang-css'
import { python } from '@codemirror/lang-python'
import { markdown } from '@codemirror/lang-markdown'
import { xml } from '@codemirror/lang-xml'
import { yaml } from '@codemirror/lang-yaml'

const props = withDefaults(defineProps<{
  modelValue: string
  fileName?: string
  readonly?: boolean
  theme?: 'dark' | 'light'
  extraExtensions?: any[]
}>(), {
  fileName: '',
  readonly: false,
  theme: 'dark',
  extraExtensions: () => [],
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  save: []
  error: [message: string]
}>()

const editorRef = ref<HTMLDivElement>()
const minimapRef = ref<HTMLCanvasElement>()

let view: EditorView | null = null
let resizeObserver: ResizeObserver | null = null
let renderTimer: ReturnType<typeof setTimeout> | undefined
let scrollHandler: (() => void) | null = null

// --- Language detection ---

const languageFactories: Record<string, () => LanguageSupport> = {
  '.json': () => json(),
  '.js': () => javascript(),
  '.mjs': () => javascript(),
  '.cjs': () => javascript(),
  '.ts': () => javascript({ typescript: true }),
  '.mts': () => javascript({ typescript: true }),
  '.cts': () => javascript({ typescript: true }),
  '.jsx': () => javascript({ jsx: true }),
  '.tsx': () => javascript({ jsx: true, typescript: true }),
  '.html': () => html(),
  '.htm': () => html(),
  '.vue': () => html(),
  '.css': () => css(),
  '.scss': () => css(),
  '.py': () => python(),
  '.pyw': () => python(),
  '.md': () => markdown(),
  '.markdown': () => markdown(),
  '.xml': () => xml(),
  '.svg': () => xml(),
  '.yaml': () => yaml(),
  '.yml': () => yaml(),
}

const langCache = new Map<string, LanguageSupport>()

function getLanguage(fileName: string): LanguageSupport | null {
  const ext = fileName.lastIndexOf('.') >= 0 ? fileName.slice(fileName.lastIndexOf('.')).toLowerCase() : ''
  if (!ext) return null
  if (!langCache.has(ext) && ext in languageFactories) {
    langCache.set(ext, languageFactories[ext]!())
  }
  return langCache.get(ext) ?? null
}

// --- Theme ---

const themeCompartment = new Compartment()

const lightTheme = EditorView.theme({
  '&': { backgroundColor: '#ffffff', color: '#333333' },
  '.cm-gutters': { backgroundColor: '#f5f5f5', color: '#999999', border: 'none' },
  '.cm-activeLineGutter': { backgroundColor: '#e8f0fe' },
  '.cm-activeLine': { backgroundColor: '#f0f4ff' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: '#333' },
  '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': { backgroundColor: '#b3d4fc !important' },
  '&.cm-focused .cm-cursor': { borderLeftColor: '#333' },
}, { dark: false })

// --- Minimap ---

const MINIMAP_MAX_SIZE = 100 * 1024

const shouldRenderMinimap = computed(() =>
  props.modelValue.length < MINIMAP_MAX_SIZE
)

function getLineColor(theme: 'dark' | 'light'): string {
  return theme === 'light' ? '#c8c8c8' : '#404040'
}

function getMinimapBg(theme: 'dark' | 'light'): string {
  return theme === 'light' ? '#f0f0f0' : '#1a1a1a'
}

function getViewportColor(theme: 'dark' | 'light'): string {
  return theme === 'light' ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.08)'
}

function renderMinimap() {
  const canvas = minimapRef.value
  if (!canvas || !view || !shouldRenderMinimap.value) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const doc = view.state.doc
  const lines = doc.lines
  const canvasWidth = canvas.width
  const canvasHeight = canvas.clientHeight

  if (lines === 0 || canvasHeight === 0) return

  canvas.width = canvasWidth
  canvas.height = canvasHeight

  const lineHeight = Math.max(1, canvasHeight / lines)

  ctx.fillStyle = getMinimapBg(props.theme)
  ctx.fillRect(0, 0, canvasWidth, canvasHeight)

  ctx.fillStyle = getLineColor(props.theme)
  for (let i = 1; i <= lines; i++) {
    const line = doc.line(i)
    const lineWidth = Math.min(line.length * 0.5, canvasWidth)
    if (lineWidth > 0) {
      ctx.fillRect(0, (i - 1) * lineHeight, lineWidth, lineHeight)
    }
  }

  // Draw viewport indicator
  const scrollDOM = view.scrollDOM
  if (scrollDOM.scrollHeight > 0) {
    const viewHeight = scrollDOM.clientHeight
    const totalHeight = scrollDOM.scrollHeight
    const scrollTop = scrollDOM.scrollTop

    const vpTop = (scrollTop / totalHeight) * canvasHeight
    const vpHeight = Math.max(lineHeight * 2, (viewHeight / totalHeight) * canvasHeight)

    ctx.fillStyle = getViewportColor(props.theme)
    ctx.fillRect(0, vpTop, canvasWidth, vpHeight)
  }
}

function scheduleMinimapRender() {
  clearTimeout(renderTimer)
  renderTimer = setTimeout(renderMinimap, 100)
}

function handleMinimapClick(e: MouseEvent) {
  if (!view || !minimapRef.value) return
  const canvas = minimapRef.value
  if (canvas.clientHeight <= 0 || view.scrollDOM.scrollHeight <= 0) return

  const fraction = e.offsetY / canvas.clientHeight
  view.scrollDOM.scrollTop = fraction * view.scrollDOM.scrollHeight
}

// --- Editor creation ---

function createExtensions() {
  const lang = getLanguage(props.fileName)
  const exts = [
    lineNumbers(),
    highlightActiveLineGutter(),
    highlightSpecialChars(),
    history(),
    drawSelection(),
    EditorState.allowMultipleSelections.of(true),
    indentOnInput(),
    bracketMatching(),
    closeBrackets(),
    keymap.of([...defaultKeymap]),
    EditorView.updateListener.of(update => {
      if (update.docChanged) {
        emit('update:modelValue', update.state.doc.toString())
        scheduleMinimapRender()
      }
    }),
    themeCompartment.of(props.theme === 'light' ? lightTheme : oneDark),
    EditorView.theme({
      '&': {
        fontFamily: "'Consolas', 'Monaco', 'Courier New', monospace",
        fontSize: '13px',
        height: '100%',
      },
      '.cm-content': {
        lineHeight: '1.6',
        tabSize: '4',
      },
      '.cm-scroller': {
        overflow: 'auto',
      },
    }),
    Prec.highest(keymap.of([{
      key: 'Mod-s',
      run: () => { emit('save'); return true },
    }])),
  ]

  if (props.readonly) {
    exts.push(EditorState.readOnly.of(true))
  }

  if (lang) {
    exts.push(lang)
  }

  for (const ext of props.extraExtensions) {
    if (ext) exts.push(ext)
  }

  return exts
}

// --- Lifecycle ---

onMounted(() => {
  try {
    view = new EditorView({
      state: EditorState.create({
        doc: props.modelValue,
        extensions: createExtensions(),
      }),
      parent: editorRef.value!,
    })

    resizeObserver = new ResizeObserver(() => {
      view?.requestMeasure()
      scheduleMinimapRender()
    })
    resizeObserver.observe(editorRef.value!)

    // Listen for scroll events to update minimap viewport
    scrollHandler = () => scheduleMinimapRender()
    view.scrollDOM.addEventListener('scroll', scrollHandler)

    // Initial minimap render
    scheduleMinimapRender()
  } catch (err) {
    console.error('CodeMirror 初始化失败:', err)
    emit('error', String(err))
  }
})

onUnmounted(() => {
  if (view && scrollHandler) {
    view.scrollDOM.removeEventListener('scroll', scrollHandler)
  }
  scrollHandler = null
  resizeObserver?.disconnect()
  resizeObserver = null
  clearTimeout(renderTimer)
  view?.destroy()
  view = null
})

// --- Watchers ---

watch(() => props.modelValue, (newVal) => {
  if (!view) return
  if (!view.hasFocus && newVal !== view.state.doc.toString()) {
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: newVal },
    })
    scheduleMinimapRender()
  }
})

watch(() => props.fileName, () => {
  if (!view) return
  // Recreate state to pick up new language extension
  view.setState(EditorState.create({
    doc: props.modelValue,
    extensions: createExtensions(),
  }))
  scheduleMinimapRender()
})

watch(() => props.theme, (newTheme) => {
  if (!view) return
  view.dispatch({
    effects: themeCompartment.reconfigure(
      newTheme === 'light' ? lightTheme : oneDark
    ),
  })
  scheduleMinimapRender()
})
</script>

<template>
  <div class="code-editor-container">
    <div ref="editorRef" class="cm-editor-wrapper" />
    <canvas
      v-if="shouldRenderMinimap"
      ref="minimapRef"
      class="cm-minimap"
      @click="handleMinimapClick"
    />
  </div>
</template>

<style scoped>
.code-editor-container {
  display: flex;
  height: 100%;
  width: 100%;
  overflow: hidden;
}

.cm-editor-wrapper {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.cm-editor-wrapper :deep(.cm-editor) {
  height: 100%;
}

.cm-editor-wrapper :deep(.cm-scroller) {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
}

.cm-minimap {
  width: 60px;
  height: 100%;
  cursor: pointer;
  flex-shrink: 0;
  border-left: 1px solid var(--border-glass);
}
</style>
