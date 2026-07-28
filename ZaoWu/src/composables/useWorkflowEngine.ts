import { ref } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { runWorkflow, stopWorkflow, confirmTool, type WorkflowEvent } from '@/services/workflow'

export function useWorkflowEngine() {
  const workflowStore = useWorkflowStore()
  const isRunning = ref(false)
  const isPaused = ref(false)
  const currentRunId = ref<string | null>(null)
  const pendingConfirmations = ref<Record<string, { nodeId: string; toolCall: Record<string, unknown> }>>({})
  const abortController = ref<AbortController | null>(null)

  function resetRuntime() {
    workflowStore.resetRuntime()
    pendingConfirmations.value = {}
    isPaused.value = false
  }

  async function start(workflowId: string, initialInput: string) {
    if (isRunning.value) return
    // 清理上一次运行残留的 AbortController
    abortController.value?.abort()
    abortController.value = null
    resetRuntime()
    isRunning.value = true

    const controller = await runWorkflow(workflowId, initialInput, {
      onEvent: (event) => handleEvent(event),
      onError: (error) => {
        // eslint-disable-next-line no-console
        console.error('workflow run error', error)
        isRunning.value = false
        isPaused.value = false
        abortController.value = null
      },
      onDone: () => {
        isRunning.value = false
        isPaused.value = false
        abortController.value = null
      },
    })
    abortController.value = controller

    return controller
  }

  async function stop() {
    // 主动 abort 前端 SSE reader，避免依赖服务端关闭流
    abortController.value?.abort()
    abortController.value = null
    isPaused.value = false
    if (!currentRunId.value || !workflowStore.workflow) return
    await stopWorkflow(workflowStore.workflow.id, currentRunId.value)
    isRunning.value = false
  }

  function handleEvent(event: WorkflowEvent) {
    if (event.runId) {
      currentRunId.value = event.runId
      workflowStore.setActiveRunId(event.runId)
    }

    switch (event.type) {
      case 'node_started':
        if (event.nodeId) {
          workflowStore.setNodeRuntime(event.nodeId, { status: 'running', inputs: event.input })
        }
        break
      case 'node_progress':
        if (event.nodeId) {
          workflowStore.setNodeRuntime(event.nodeId, { status: 'running' })
        }
        break
      case 'node_ended':
        if (event.nodeId) {
          workflowStore.setNodeRuntime(event.nodeId, {
            status: 'done',
            outputs: event.output,
            tokens: event.tokens,
            elapsedMs: event.elapsedMs,
          })
        }
        break
      case 'node_errored':
        if (event.nodeId) {
          workflowStore.setNodeRuntime(event.nodeId, {
            status: 'error',
            error: event.error,
          })
        }
        break
      case 'edge_crossed':
        // 数据沿边流动：激活对应边的脉冲动画，1.5s 后自动熄灭
        if (event.sourceNodeId && event.targetNodeId) {
          const edge = workflowStore.edges.find(
            (e) => e.source === event.sourceNodeId && e.target === event.targetNodeId
          )
          if (edge) {
            workflowStore.setEdgeActive(edge.id, true)
            setTimeout(() => workflowStore.setEdgeActive(edge.id, false), 1500)
          }
        }
        break
      case 'node_requires_confirmation':
        if (event.nodeId && event.toolCall) {
          const requestId = String(event.toolCall.requestId || '')
          pendingConfirmations.value[requestId] = {
            nodeId: event.nodeId,
            toolCall: event.toolCall,
          }
        }
        break
      case 'wf_paused':
        // 工作流暂停等待工具确认
        isPaused.value = true
        break
      case 'wf_resumed':
        isPaused.value = false
        break
      case 'wf_completed':
      case 'wf_errored':
        isRunning.value = false
        isPaused.value = false
        break
    }
  }

  async function submitConfirmation(requestId: string, approved: boolean) {
    const pending = pendingConfirmations.value[requestId]
    if (!pending || !workflowStore.workflow || !currentRunId.value) return
    await confirmTool(workflowStore.workflow.id, currentRunId.value, requestId, approved)
    delete pendingConfirmations.value[requestId]
  }

  return {
    isRunning,
    isPaused,
    currentRunId,
    pendingConfirmations,
    start,
    stop,
    submitConfirmation,
  }
}
