<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { useEditorStore } from '@/stores/editor'
import type { SearchResult, ContentMatch, FilenameMatch } from '@/types'

const props = defineProps<{
  results: SearchResult[]
  query: string
}>()

const { t } = useI18n()
const editorStore = useEditorStore()

function openFile(path: string) {
  editorStore.openFile(path)
}

function getFileName(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || path
}

function getDirPath(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/')
  parts.pop()
  return parts.join('/')
}

function highlightText(text: string, query: string): string {
  if (!query) return escapeHtml(text)
  const regex = new RegExp(`(${escapeRegex(query)})`, 'gi')
  return escapeHtml(text).replace(regex, '<mark>$1</mark>')
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function getContentSnippet(match: ContentMatch, query: string): string {
  const line = match.content
  const start = Math.max(0, match.startIndex - 30)
  const end = Math.min(line.length, match.endIndex + 30)
  let snippet = line.slice(start, end)
  if (start > 0) snippet = '...' + snippet
  if (end < line.length) snippet = snippet + '...'
  return highlightText(snippet, query)
}
</script>

<template>
  <div class="search-results">
    <div v-for="result in results" :key="result.path" class="result-file">
      <div class="result-file-header" @click="openFile(result.path)">
        <span class="file-name">{{ getFileName(result.path) }}</span>
        <span class="file-path" :title="result.path">{{ getDirPath(result.path) }}</span>
      </div>
      <div v-for="(match, idx) in result.matches" :key="idx" class="result-match">
        <template v-if="match.type === 'content'">
          <span class="match-line">{{ match.line }}</span>
          <span class="match-content" v-html="getContentSnippet(match, query)"></span>
        </template>
        <template v-else>
          <span class="match-filename">{{ t('search.fileName') }}</span>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-results {
  padding: 0 4px;
}

.result-file {
  margin-bottom: 8px;
}

.result-file-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.result-file-header:hover {
  background: var(--bg-glass-hover);
}

.file-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  flex-shrink: 0;
}

.file-path {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

.result-match {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 3px 8px 3px 24px;
  font-size: 12px;
  border-radius: 4px;
  transition: background 0.15s;
}

.result-match:hover {
  background: var(--bg-glass-hover);
}

.match-line {
  flex-shrink: 0;
  min-width: 28px;
  text-align: right;
  color: var(--text-tertiary);
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 11px;
}

.match-content {
  flex: 1;
  min-width: 0;
  color: var(--text-secondary);
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.match-content :deep(mark) {
  background: rgba(0, 122, 255, 0.25);
  color: var(--accent);
  border-radius: 2px;
  padding: 0 1px;
}

.match-filename {
  color: var(--text-tertiary);
  font-size: 11px;
  font-style: italic;
}
</style>
