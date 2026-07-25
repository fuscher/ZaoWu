<script setup lang="ts">
import { computed } from 'vue'
import BaseNode from './BaseNode.vue'
import type { NodeProps } from '@vue-flow/core'
import { useWorkflowStore } from '@/stores/workflow'

const props = defineProps<NodeProps>()
const workflowStore = useWorkflowStore()

const label = computed(() => (props.data?.label as string) || '条件分支')
const runtime = computed(() => workflowStore.nodeRuntime[props.id])
const status = computed(() => runtime.value?.status ?? 'idle')
</script>

<template>
  <BaseNode
    :id="props.id"
    :status="status"
    :label="label"
    icon-name="GitBranch"
    :inputs="['default']"
    :outputs="['true', 'false']"
  />
</template>
