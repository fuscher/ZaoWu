/**
 * Stage 10 — Workflow Store 单元测试
 *
 * 验证：
 * - setWorkflow 重置运行时状态
 * - updateNodeConfig 更新节点配置
 * - setNodeRuntime / resetRuntime 管理节点运行时信息
 * - selectedNode 计算属性正确返回选中节点
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWorkflowStore } from '@/stores/workflow'
import type { WorkflowDefinition, WorkflowNode } from '@/types/workflow'

describe('Workflow Store', () => {
  let store: ReturnType<typeof useWorkflowStore>

  const sampleWorkflow: WorkflowDefinition = {
    id: 'wf-test',
    name: 'Test Workflow',
    version: 1,
    nodes: [
      { id: 'start', type: 'start', position: { x: 0, y: 0 }, label: 'Start', config: { defaultValue: 'hello' } },
      { id: 'llm', type: 'llm', position: { x: 200, y: 0 }, label: 'LLM', config: {} },
    ],
    edges: [],
    variables: [],
    executionConfig: { autoApproveWrites: false },
    createdAt: Date.now(),
    updatedAt: Date.now(),
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useWorkflowStore()
  })

  it('setWorkflow 加载定义并重置运行时状态', () => {
    store.setWorkflow(sampleWorkflow)
    expect(store.workflow).toEqual(sampleWorkflow)
    expect(store.nodeRuntime).toEqual({})
    expect(store.activeRunId).toBeNull()
  })

  it('selectedNode 返回当前选中的节点', () => {
    store.setWorkflow(sampleWorkflow)
    store.selectNode('llm')
    expect(store.selectedNode?.id).toBe('llm')
    expect(store.selectedNode?.type).toBe('llm')
  })

  it('updateNodeConfig 更新指定节点配置', () => {
    store.setWorkflow(sampleWorkflow)
    store.updateNodeConfig('llm', { slots: { model: { providerId: 'p1', modelId: 'gpt-4o' } } })
    const node = store.workflow?.nodes.find(n => n.id === 'llm') as WorkflowNode
    expect(node.config.slots?.model?.providerId).toBe('p1')
    expect(node.config.slots?.model?.modelId).toBe('gpt-4o')
  })

  it('setNodeRuntime 按节点 ID 累积运行时信息', () => {
    store.setWorkflow(sampleWorkflow)
    store.setNodeRuntime('llm', { status: 'running' })
    store.setNodeRuntime('llm', { tokens: 42 })
    expect(store.nodeRuntime['llm']).toEqual({ status: 'running', tokens: 42 })
  })

  it('resetRuntime 清空节点运行时信息', () => {
    store.setWorkflow(sampleWorkflow)
    store.setNodeRuntime('llm', { status: 'done' })
    store.resetRuntime()
    expect(store.nodeRuntime).toEqual({})
  })
})
