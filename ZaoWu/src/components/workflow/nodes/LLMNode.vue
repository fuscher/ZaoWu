<script setup lang="ts">
import { computed } from 'vue'
import BaseNode from './BaseNode.vue'
import type { NodeProps } from '@vue-flow/core'
import { useWorkflowStore } from '@/stores/workflow'

const props = defineProps<NodeProps>()
const workflowStore = useWorkflowStore()

const label = computed(() => (props.data?.label as string) || 'LLM 节点')
const runtime = computed(() => workflowStore.nodeRuntime[props.id])
const status = computed(() => runtime.value?.status ?? 'idle')
const tokens = computed(() => runtime.value?.tokens)
</script>

<template>
  <BaseNode
    :id="props.id"
    :status="status"
    :tokens="tokens"
    :label="label"
    icon-name="Bot"
    :inputs="['default']"
    :outputs="['default']"
  />
</template>
