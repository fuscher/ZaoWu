<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { useGitStore } from '@/stores/git'
import type { GitBranch } from '@/types'

const emit = defineEmits<{ close: []; select: [branch: string] }>()
const { t } = useI18n()
const gitStore = useGitStore()
const searchQuery = ref('')

function open() {
  gitStore.fetchBranches()
}

const localBranches = computed(() =>
  gitStore.branches.filter(b => !b.isRemote && b.name.toLowerCase().includes(searchQuery.value.toLowerCase()))
)
const remoteBranches = computed(() =>
  gitStore.branches.filter(b => b.isRemote && b.name.toLowerCase().includes(searchQuery.value.toLowerCase()))
)

open()
</script>

<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog">
      <div class="dialog-header">
        <span class="dialog-title">{{ t('git.selectBranch') }}</span>
        <button class="dialog-close" @click="emit('close')">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
      </div>
      <div class="dialog-search">
        <svg class="dialog-search-icon" width="12" height="12" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4.5" stroke="currentColor" stroke-width="1.2"/><path d="M9.5 9.5L13 13" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
        <input
          v-model="searchQuery"
          class="dialog-search-input"
          :placeholder="t('git.searchBranch')"
        />
      </div>
      <div class="dialog-body">
        <div v-if="localBranches.length === 0 && remoteBranches.length === 0" class="dialog-empty">
          {{ searchQuery ? t('git.noMatchingBranches') : t('git.noBranches') }}
        </div>
        <template v-else>
          <div v-if="localBranches.length > 0" class="dialog-section">
            <div class="dialog-section-label">Local</div>
            <div
              v-for="b in localBranches"
              :key="'l-' + b.name"
              class="dialog-item"
              :class="{ active: b.isCurrent }"
              @click="emit('select', b.name)"
            >
              <svg class="dialog-item-icon" width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 2v5l3 3 3-3V2H3z" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
              <span class="dialog-item-name">{{ b.name }}</span>
              <span v-if="b.isCurrent" class="dialog-item-badge">{{ t('git.currentBranch', { name: '' }).replace(': ', '') }}</span>
            </div>
          </div>
          <div v-if="remoteBranches.length > 0" class="dialog-section">
            <div class="dialog-section-label">Remote</div>
            <div
              v-for="b in remoteBranches"
              :key="'r-' + b.name"
              class="dialog-item"
              @click="emit('select', b.name)"
            >
              <svg class="dialog-item-icon" width="12" height="12" viewBox="0 0 12 12" fill="none"><circle cx="6" cy="6" r="3" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
              <span class="dialog-item-name">{{ b.name }}</span>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border-glass);
  border-radius: 12px;
  width: 400px;
  max-height: 60vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.3);
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-subtle);
}

.dialog-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.dialog-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
}

.dialog-close:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}

.dialog-search {
  position: relative;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.dialog-search-icon {
  position: absolute;
  left: 28px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
}

.dialog-search-input {
  width: 100%;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 8px 10px 8px 30px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.dialog-search-input:focus {
  border-color: var(--accent);
}

.dialog-search-input::placeholder {
  color: var(--text-tertiary);
}

.dialog-body {
  padding: 8px;
  overflow-y: auto;
  flex: 1;
}

.dialog-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
}

.dialog-section {
  margin-bottom: 4px;
}

.dialog-section-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  padding: 6px 12px 2px;
}

.dialog-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background var(--transition);
}

.dialog-item:hover {
  background: var(--bg-glass-hover);
}

.dialog-item.active {
  background: var(--accent-muted);
}

.dialog-item-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.dialog-item-name {
  font-size: 13px;
  color: var(--text-primary);
}

.dialog-item-badge {
  font-size: 10px;
  color: var(--accent);
  background: var(--accent-muted);
  padding: 1px 6px;
  border-radius: 4px;
}
</style>
