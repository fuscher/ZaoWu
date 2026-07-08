<script setup lang="ts">
import { computed } from 'vue'
import { Search, X, Loader } from '@lucide/vue'
import { useI18n } from '@/i18n'
import { useSearchStore } from '@/stores/search'
import SearchResults from './SearchResults.vue'

const { t } = useI18n()
const store = useSearchStore()

const hasResults = computed(() => store.results.length > 0)
const hasQuery = computed(() => store.query.trim().length > 0)

function onInput(e: Event) {
  store.query = (e.target as HTMLInputElement).value
}

async function cancel() {
  await store.cancelSearch()
}
</script>

<template>
  <div class="search-panel">
    <div class="search-box">
      <Search class="search-icon" :size="14" />
      <input
        type="text"
        :value="store.query"
        :placeholder="t('search.placeholder')"
        class="search-input"
        @input="onInput"
      />
      <button v-if="store.isSearching" class="cancel-btn" :title="t('search.cancel')" @click="cancel">
        <X :size="14" />
      </button>
    </div>

    <div v-if="store.isSearching" class="search-status">
      <Loader :size="14" class="spin" />
      <span>{{ t('search.searching') }}</span>
    </div>

    <div v-else-if="hasQuery && hasResults" class="result-summary">
      {{ t('search.resultCount', { files: store.totalFiles, matches: store.totalMatches }) }}
    </div>

    <div v-else-if="hasQuery && !store.isSearching && !hasResults" class="no-results">
      {{ t('search.noResults') }}
    </div>

    <div v-if="hasResults" class="results-container">
      <SearchResults :results="store.results" :query="store.query" />
    </div>
  </div>
</template>

<style scoped>
.search-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.search-box {
  position: relative;
  padding: 8px;
  border-bottom: 1px solid var(--border-subtle);
}

.search-icon {
  position: absolute;
  left: 18px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
}

.search-input {
  width: 100%;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  padding: 8px 32px 8px 32px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.search-input::placeholder {
  color: var(--text-tertiary);
}

.search-input:focus {
  border-color: var(--accent);
}

.cancel-btn {
  position: absolute;
  right: 18px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
}

.cancel-btn:hover {
  color: var(--text-secondary);
  background: var(--bg-glass-hover);
}

.search-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.result-summary {
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-subtle);
}

.no-results {
  padding: 24px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--text-tertiary);
}

.results-container {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
</style>
