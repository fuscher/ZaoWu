import { ref } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { runWorkflow, stopWorkflow, confirmTool, type WorkflowEvent } from '@/services/workflow'

export function useWorkflowEngine() {
  const workflowStore = useWorkflowStore()
  const isRunning = ref(false)
  const currentRunId = ref<string | null>(null)
  const pendingConfirmations = ref<Record<string, { nodeId: string; toolCall: Record<string, unknown> }>>({})

  function resetRuntime() {
    workflowStore.resetRuntime()
    pendingConfirmations.value = {}
  }

  async function start(workflowId: string, initialInput: string) {
    if (isRunning.value) return
    resetRuntime()
    isRunning.value = true

    const controller = await runWorkflow(workflowId, initialInput, {
      onEvent: (event) => handleEvent(event),
      onError: (error) => {
        // eslint-disable-next-line no-console
        console.error('workflow run error', error)
        isRunning.value = false
      },
      onDone: () => {
        isRunning.value = false
      },
    })

    return controller
  }

  async function stop() {
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
      case 'node_requires_confirmation':
        if (event.nodeId && event.toolCall) {
          const requestId = String(event.toolCall.requestId || '')
          pendingConfirmations.value[requestId] = {
            nodeId: event.nodeId,
            toolCall: event.toolCall,
          }
        }
        break
      case 'wf_completed':
      case 'wf_errored':
        isRunning.value = false
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
    currentRunId,
    pendingConfirmations,
    start,
    stop,
    submitConfirmation,
  }
}
