<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ChevronDown, Cpu, RefreshCw } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'
import { updateConversation } from '@/services/ai'

const chatStore = useChatStore()
const { t } = useI18n()
const isOpen = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)

const currentModelName = computed(() => {
  const conv = chatStore.currentConversation
  if (!conv) return t('chat.selectModel')
  const provider = chatStore.providers.find((p) => p.id === conv.providerId)
  if (!provider) return t('chat.selectModel')
  const model = provider.models?.find((m) => m.id === conv.modelId)
  return model?.name || conv.modelId || t('chat.selectModel')
})

function toggle() {
  isOpen.value = !isOpen.value
}

async function selectModel(providerId: string, modelId: string) {
  if (chatStore.currentConversation) {
    chatStore.currentConversation.providerId = providerId
    chatStore.currentConversation.modelId = modelId
    await updateConversation(chatStore.currentConversation.id, { providerId, modelId })
  } else {
    chatStore.updateConfig({ defaultProviderId: providerId, defaultModelId: modelId })
  }
  isOpen.value = false
}

async function refreshModels(providerId: string) {
  await chatStore.refreshModels(providerId)
}

function handleClickOutside(e: Event) {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))
</script>

<template>
  <div class="model-switcher" ref="dropdownRef">
    <button class="switcher-trigger" @click="toggle">
      <Cpu :size="14" />
      <span class="model-name">{{ currentModelName }}</span>
      <ChevronDown :size="12" class="chevron" :class="{ open: isOpen }" />
    </button>

    <Transition name="dropdown">
      <div v-if="isOpen" class="dropdown">
        <div v-if="chatStore.providers.length === 0" class="dropdown-empty">
          {{ t('chat.noProviders') }}
        </div>
        <template v-else>
          <div v-for="provider in chatStore.providers" :key="provider.id" class="provider-group">
            <div class="provider-header">
              <span class="provider-name">{{ provider.name }}</span>
              <button class="refresh-btn" :title="t('chat.refreshModels')" @click.stop="refreshModels(provider.id)">
                <RefreshCw :size="11" />
              </button>
            </div>
            <div
              v-for="model in provider.models"
              :key="model.id"
              class="model-option"
              :class="{ active: chatStore.currentConversation?.modelId === model.id }"
              @click="selectModel(provider.id, model.id)"
            >
              <span class="model-id">{{ model.name || model.id }}</span>
              <span v-if="model.contextLength" class="model-ctx">{{ Math.round(model.contextLength / 1000) }}k</span>
            </div>
            <div v-if="provider.models.length === 0" class="model-empty">
              {{ t('chat.noModels') }}
            </div>
          </div>
        </template>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.model-switcher {
  position: relative;
}

.switcher-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  transition: all var(--transition);
  white-space: nowrap;
}

.switcher-trigger:hover {
  background: var(--bg-glass-hover);
  border-color: var(--border-hover);
}

.model-name {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chevron {
  transition: transform var(--transition);
}

.chevron.open {
  transform: rotate(180deg);
}

.dropdown {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 0;
  min-width: 220px;
  max-height: 300px;
  overflow-y: auto;
  background: var(--bg-primary);
  border: 1px solid var(--border-glass);
  border-radius: 10px;
  padding: 6px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  z-index: 100;
}

.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.15s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.dropdown-empty {
  padding: 12px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}

.provider-group {
  margin-bottom: 4px;
}

.provider-group:last-child {
  margin-bottom: 0;
}

.provider-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
}

.provider-name {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.refresh-btn {
  width: 20px;
  height: 20px;
  border: none;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
}

.refresh-btn:hover {
  background: var(--bg-glass);
  color: var(--accent);
}

.model-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background var(--transition);
}

.model-option:hover {
  background: var(--bg-glass-hover);
}

.model-option.active {
  background: var(--accent-muted);
  color: var(--accent);
}

.model-id {
  font-size: 12px;
  color: var(--text-primary);
}

.model-option.active .model-id {
  color: var(--accent);
}

.model-ctx {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 1px 5px;
  border-radius: 3px;
}

.model-empty {
  padding: 8px 10px;
  font-size: 11px;
  color: var(--text-tertiary);
}
</style>
