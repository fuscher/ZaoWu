<template>
  <div
    class="cau-readme-panel"
    :class="[`cau-readme-panel--theme-${effectiveTheme}`]"
  >
    <div v-if="!enabled" class="cau-readme-empty">
      README {{ t('disabled') }}
    </div>
    <div v-else-if="error" class="cau-readme-error">{{ error }}</div>
    <div v-else-if="loading && !content" class="cau-readme-empty">
      {{ t('loading') }}
    </div>
    <div v-else ref="contentEl" class="cau-readme-content" v-html="rendered" @click="onContentClick" />
  </div>
</template>

<script setup lang="ts">
import {
  ref,
  computed,
  onMounted,
  onUnmounted,
  watch,
} from 'vue'
import MarkdownIt from 'markdown-it'
import { usePluginsStore } from '@/stores/plugins'

const props = defineProps<{
  pluginName?: string
}>()

const pluginsStore = usePluginsStore()

const content = ref('')
const mtime = ref<number | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const hostTheme = ref('dark')
const contentEl = ref<HTMLElement | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let themeObserver: MutationObserver | null = null

function readHostTheme(): string {
  return document.documentElement.getAttribute('data-theme') || 'dark'
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\w\u4e00-\u9fa5]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

const plugin = computed(() =>
  pluginsStore.plugins.find((p) => p.name === 'code_assistant_utils'),
)

const cfg = computed(() => {
  const c = plugin.value?.config ?? {}
  return {
    enabled: c.readme_enabled !== false,
    theme: (c.readme_theme as string) || 'auto',
    refreshSeconds: Math.max(5, Number(c.readme_refresh_seconds) || 10),
  }
})

const enabled = computed(() => cfg.value.enabled)

const effectiveTheme = computed(() => {
  if (cfg.value.theme === 'auto') {
    return hostTheme.value === 'light' ? 'light' : 'dark'
  }
  return cfg.value.theme
})

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const defaultImageRender =
  md.renderer.rules.image ||
  ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))

md.renderer.rules.image = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const srcIndex = token.attrIndex('src')
  if (srcIndex >= 0) {
    const src = token.attrs![srcIndex][1]
    token.attrs![srcIndex][1] = resolveImageUrl(src)
  }
  return defaultImageRender(tokens, idx, options, env, self)
}

const defaultHeadingOpenRender =
  md.renderer.rules.heading_open ||
  ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))

md.renderer.rules.heading_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const next = tokens[idx + 1]
  if (next && next.type === 'inline') {
    const id = slugify(next.content)
    if (id) {
      const idxAttr = token.attrIndex('id')
      if (idxAttr >= 0) {
        token.attrs![idxAttr][1] = id
      } else {
        token.attrPush(['id', id])
      }
    }
  }
  return defaultHeadingOpenRender(tokens, idx, options, env, self)
}

function resolveImageUrl(src: string): string {
  if (!src || /^(https?:|data:|\/\/)/i.test(src)) return src
  return `/api/plugins/code_assistant_utils/readme-asset?src=${encodeURIComponent(src)}`
}

const rendered = computed(() => md.render(content.value || ''))

function onContentClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  const anchor = target.closest('a') as HTMLAnchorElement | null
  if (!anchor || !contentEl.value) return

  const href = anchor.getAttribute('href')
  if (!href) return

  // 锚点跳转：在当前面板内平滑滚动
  if (href.startsWith('#')) {
    event.preventDefault()
    const id = decodeURIComponent(href.slice(1))
    const el = contentEl.value.querySelector(`[id="${CSS.escape(id)}"]`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    return
  }

  // 外部链接：新标签/系统浏览器打开
  if (/^(https?:|mailto:|tel:)/i.test(href)) {
    event.preventDefault()
    window.open(href, '_blank', 'noopener,noreferrer')
    return
  }
}

function t(key: string): string {
  const messages: Record<string, string> = {
    disabled: '展示已禁用 / display disabled',
    loading: '加载中... / Loading...',
  }
  return messages[key] ?? key
}

async function loadReadme(force = false) {
  if (!enabled.value) return
  loading.value = true
  error.value = null
  try {
    const res = await fetch('/api/plugins/code_assistant_utils/readme')
    const data = await res.json()
    if (!data.ok) {
      error.value = data.error || 'Failed to load README'
      return
    }
    if (force || mtime.value === null || data.mtime !== mtime.value) {
      content.value = data.content
      mtime.value = data.mtime
    }
  } catch (e: any) {
    error.value = e.message || 'Request failed'
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  loadReadme(true)
  timer = setInterval(() => loadReadme(false), cfg.value.refreshSeconds * 1000)
}

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

watch(
  () => cfg.value.enabled,
  (isEnabled) => {
    if (isEnabled) startPolling()
    else stopPolling()
  },
)

watch(
  () => cfg.value.refreshSeconds,
  () => {
    if (enabled.value) startPolling()
  },
)

onMounted(() => {
  hostTheme.value = readHostTheme()
  themeObserver = new MutationObserver(() => {
    hostTheme.value = readHostTheme()
  })
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  })
  if (enabled.value) startPolling()
})

onUnmounted(() => {
  stopPolling()
  themeObserver?.disconnect()
  themeObserver = null
})
</script>

<style scoped>
.cau-readme-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px;
  max-height: 420px;
  overflow-y: auto;
}

.cau-readme-empty {
  color: var(--text-tertiary);
  font-size: 12px;
  text-align: center;
  padding: 16px;
}

.cau-readme-error {
  color: var(--danger);
  font-size: 12px;
  padding: 8px 12px;
  background: var(--danger-muted);
  border-radius: 6px;
}

.cau-readme-content {
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-primary);
}

.cau-readme-content :deep(h1) {
  font-size: 16px;
  margin: 12px 0 8px;
}

.cau-readme-content :deep(h2) {
  font-size: 14px;
  margin: 10px 0 6px;
}

.cau-readme-content :deep(h3) {
  font-size: 13px;
  margin: 8px 0 4px;
}

.cau-readme-content :deep(h4),
.cau-readme-content :deep(h5),
.cau-readme-content :deep(h6) {
  font-size: 13px;
  margin: 6px 0 4px;
}

.cau-readme-content :deep(p) {
  margin: 6px 0;
}

.cau-readme-content :deep(ul),
.cau-readme-content :deep(ol) {
  padding-left: 20px;
  margin: 6px 0;
}

.cau-readme-content :deep(li) {
  margin: 2px 0;
}

.cau-readme-content :deep(code) {
  background: var(--bg-glass);
  padding: 2px 5px;
  border-radius: 4px;
  font-family: var(--font-mono, monospace);
  font-size: 12px;
}

.cau-readme-content :deep(pre) {
  background: var(--bg-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 10px;
  overflow-x: auto;
}

.cau-readme-content :deep(pre code) {
  background: none;
  padding: 0;
}

.cau-readme-content :deep(img) {
  max-width: 100%;
  border-radius: 4px;
}

.cau-readme-content :deep(a) {
  color: var(--accent);
  text-decoration: none;
}

.cau-readme-content :deep(a:hover) {
  text-decoration: underline;
}

.cau-readme-content :deep(hr) {
  border: none;
  border-top: 1px solid var(--border-subtle);
  margin: 12px 0;
}

.cau-readme-content :deep(blockquote) {
  margin: 6px 0;
  padding-left: 12px;
  border-left: 3px solid var(--border-subtle);
  color: var(--text-secondary);
}

.cau-readme-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin: 8px 0;
}

.cau-readme-content :deep(th),
.cau-readme-content :deep(td) {
  border: 1px solid var(--border-subtle);
  padding: 6px 8px;
  text-align: left;
}

.cau-readme-content :deep(th) {
  background: var(--bg-glass);
}
</style>