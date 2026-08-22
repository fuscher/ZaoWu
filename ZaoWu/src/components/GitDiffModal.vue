<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'

const props = defineProps<{
  file?: string
  staged?: boolean
}>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const gitStore = useGitStore()
const diffContent = ref('')
const loading = ref(true)

onMounted(async () => {
  const result = await gitStore.getFileDiff(props.file, props.staged)
  diffContent.value = result.diff || result.error || t('git.noDiff')
  loading.value = false
})

function formatDiffLine(line: string): string {
  return line
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <div class="modal-header">
        <span class="modal-title">{{ t('git.diff') }} {{ file || '' }}</span>
        <button class="modal-close" @click="emit('close')">×</button>
      </div>
      <div class="modal-body">
        <div v-if="loading" class="loading">{{ t('git.loading') }}</div>
        <pre v-else class="diff-content">{{ diffContent }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: var(--bg-primary);
  border: 1px solid var(--border-glass);
  border-radius: 12px;
  width: 80vw;
  max-width: 900px;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.3);
}
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-subtle);
}
.modal-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.modal-close {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 16px;
}
.modal-body {
  flex: 1;
  overflow: auto;
  padding: 16px;
}
.loading {
  text-align: center;
  color: var(--text-tertiary);
  padding: 40px;
}
.diff-content {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre;
  color: var(--text-primary);
  margin: 0;
}
</style>
