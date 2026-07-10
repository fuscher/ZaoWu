<script setup lang="ts">
import { computed } from 'vue'
import { yCollab } from 'y-codemirror.next'
import CodeEditor from './CodeEditor.vue'
import type * as Y from 'yjs'
import type { Awareness } from 'y-protocols/awareness'

const props = defineProps<{
  ytext: Y.Text
  awareness: Awareness
  fileName?: string
  theme?: 'dark' | 'light'
  readonly?: boolean
}>()

const emit = defineEmits<{
  save: []
}>()

const collabExtension = computed(() => yCollab(props.ytext, props.awareness))
</script>

<template>
  <CodeEditor
    :model-value="ytext.toString()"
    :file-name="fileName || ''"
    :theme="theme || 'dark'"
    :readonly="readonly"
    :extra-extensions="[collabExtension]"
    @save="emit('save')"
  />
</template>
