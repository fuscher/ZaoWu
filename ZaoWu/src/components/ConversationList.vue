<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { Plus, Search, MessageSquare, Trash2, Pencil, Check, X } from '@lucide/vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from '@/i18n'

const chatStore = useChatStore()
const { t } = useI18n()
const searchQuery = ref('')
const editingId = ref<string | null>(null)
const editTitle = ref('')

const filteredConversations = computed(() => {
  if (!searchQuery.value.trim()) return chatStore.conversations
  const q = searchQuery.value.toLowerCase()
  return chatStore.conversations.filter((c) => c.title.toLowerCase().includes(q))
})

async function handleNew() {
  await chatStore.createNewConversation()
}

function handleSelect(id: string) {
  if (editingId.value === id) return
  chatStore.switchConversation(id)
}

function startEdit(conv: { id: string; title: string }) {
  editingId.value = conv.id
  editTitle.value = conv.title
  nextTick(() => {
    const input = document.querySelector('.edit-input') as HTMLInputElement
    input?.focus()
  })
}

function confirmEdit(id: string) {
  if (editTitle.value.trim()) {
    chatStore.renameConversation(id, editTitle.value.trim())
  }
  editingId.value = null
}

function cancelEdit() {
  editingId.value = null
}

function handleDelete(e: Event, id: string) {
  e.stopPropagation()
  chatStore.removeConversation(id)
}
</script>

<template>
  <div class="conversation-list">
    <div class="conv-toolbar">
      <button class="new-btn" :title="t('chat.newConversation')" @click="handleNew">
        <Plus :size="14" />
      </button>
      <div class="conv-search">
        <Search :size="12" class="search-icon" />
        <input
          v-model="searchQuery"
          :placeholder="t('chat.searchConversations')"
          class="search-input"
        />
      </div>
    </div>

    <div class="conv-items">
      <div
        v-for="conv in filteredConversations"
        :key="conv.id"
        class="conv-item"
        :class="{ active: chatStore.currentConversation?.id === conv.id }"
        @click="handleSelect(conv.id)"
      >
        <MessageSquare :size="14" class="conv-icon" />
        <div class="conv-info">
          <template v-if="editingId === conv.id">
            <div class="edit-row">
              <input
                v-model="editTitle"
                class="edit-input"
                @keydown.enter="confirmEdit(conv.id)"
                @keydown.escape="cancelEdit"
                @blur="confirmEdit(conv.id)"
              />
              <button class="edit-action" @mousedown.prevent="confirmEdit(conv.id)">
                <Check :size="12" />
              </button>
              <button class="edit-action" @mousedown.prevent="cancelEdit">
                <X :size="12" />
              </button>
            </div>
          </template>
          <template v-else>
            <span class="conv-title">{{ conv.title }}</span>
          </template>
          <span class="conv-meta">{{ conv.messageCount }} {{ t('chat.messages') }}</span>
        </div>
        <div class="conv-actions">
          <button
            class="action-btn"
            :title="t('chat.renameConversation')"
            @click.stop="startEdit(conv)"
          >
            <Pencil :size="12" />
          </button>
          <button
            class="action-btn danger"
            :title="t('chat.deleteConversation')"
            @click="handleDelete($event, conv.id)"
          >
            <Trash2 :size="12" />
          </button>
        </div>
      </div>

      <div v-if="filteredConversations.length === 0" class="conv-empty">
        <span>{{ searchQuery ? t('chat.noResults') : t('chat.noConversations') }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.conversation-list {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.conv-toolbar {
  display: flex;
  gap: 6px;
  padding: 4px 0 8px;
}

.new-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass);
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition);
}

.new-btn:hover {
  background: var(--accent-muted);
  color: var(--accent);
  border-color: var(--accent);
}

.conv-search {
  flex: 1;
  position: relative;
}

.search-icon {
  position: absolute;
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
}

.search-input {
  width: 100%;
  background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: 6px;
  padding: 5px 8px 5px 26px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
}

.search-input::placeholder {
  color: var(--text-tertiary);
}

.search-input:focus {
  border-color: var(--accent);
}

.conv-items {
  flex: 1;
  overflow-y: auto;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background var(--transition);
  position: relative;
}

.conv-item:hover {
  background: var(--bg-glass-hover);
}

.conv-item.active {
  background: var(--accent-muted);
}

.conv-item:hover .conv-actions {
  opacity: 1;
}

.conv-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.conv-info {
  flex: 1;
  min-width: 0;
}

.conv-title {
  font-size: 13px;
  color: var(--text-primary);
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-meta {
  font-size: 11px;
  color: var(--text-tertiary);
}

.edit-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.edit-input {
  flex: 1;
  background: var(--bg-primary);
  border: 1px solid var(--accent);
  border-radius: 4px;
  padding: 2px 6px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  min-width: 0;
}

.edit-action {
  width: 18px;
  height: 18px;
  border: none;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  flex-shrink: 0;
}

.edit-action:hover {
  color: var(--accent);
  background: var(--bg-glass);
}

.conv-actions {
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity var(--transition);
}

.action-btn {
  width: 22px;
  height: 22px;
  border: none;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
}

.action-btn:hover {
  background: var(--bg-glass);
  color: var(--text-secondary);
}

.action-btn.danger:hover {
  color: var(--danger);
}

.conv-empty {
  text-align: center;
  padding: 24px 8px;
  color: var(--text-tertiary);
  font-size: 12px;
}
</style>
