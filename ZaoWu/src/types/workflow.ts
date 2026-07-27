/**
 * Stage 10: 工作流（Workflow）类型定义
 *
 * 设计原则：
 * - 与 Python 侧 workflow_engine/schema.py 保持语义对齐
 * - Vue Flow 视觉类型（edge.type）与业务边类型（edge.edgeType）分离
 * - camelCase 作为前后端线协议键名
 */

export type NodeType =
  | 'start'
  | 'llm'
  | 'condition'
  | 'tool'
  | 'loop'
  | 'end'

export type EdgeType = 'data' | 'condition'

export type NodeStatus = 'idle' | 'running' | 'done' | 'error'

export interface Position {
  x: number
  y: number
}

export interface WorkflowDefinition {
  id: string
  name: string
  description?: string
  version: number
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  variables: WorkflowVariable[]
  executionConfig: WorkflowExecutionConfig
  createdAt: number
  updatedAt: number
  lastRunAt?: number
  runCount?: number
}

export interface WorkflowNode {
  id: string
  type: NodeType
  position: Position
  label: string
  config: NodeConfig
  retryConfig?: RetryConfig
  inputMapping?: InputMapping[]
  outputExpose?: OutputExpose[]
}

export interface WorkflowEdge {
  id: string
  source: string
  sourcePort: string
  target: string
  targetPort: string
  // Vue Flow 视觉渲染类型
  type: string
  // 业务语义类型
  edgeType: EdgeType
  condition?: Record<string, unknown>
  dataContract?: DataContract
  label?: string
}

export interface NodeConfig {
  slots?: {
    model?: ModelSlot
    prompt?: PromptSlot
    expert?: ExpertSlot
    skills?: SkillSlot[]
    mcp?: MCPSlot[]
  }
  conditionConfig?: ConditionConfig
  loopConfig?: LoopConfig
  toolName?: string
  toolArgs?: Record<string, string>
  /** @deprecated 使用 endMode + logFormat 替代 */
  outputFormat?: 'text' | 'json' | 'markdown'
  endMode?: 'none' | 'log'
  logFormat?: 'json' | 'markdown' | 'txt'
  logDir?: string
  logName?: string
  // Start 节点默认值（UI 配置使用）
  defaultValue?: string
  // LLM 工具调用循环
  maxToolIterations?: number
  toolLoopThreshold?: number
  // Start 节点执行模式
  executionMode?: 'parallel' | 'ordered'
  orderedTargets?: string[]
}

export interface ModelSlot {
  providerId: string
  modelId: string
  temperature?: number
  /** 最大输出 token 数。undefined 表示自动推算（基于模型 contextLength 的 1/2）。 */
  maxTokens?: number
  inheritFrom?: 'component' | 'global'
}

export interface PromptSlot {
  template: string
  systemPrompt?: string
  version: number
  history?: PromptVersion[]
}

export interface PromptVersion {
  version: number
  template: string
  changedAt: number
  changedBy: string
  diffFromPrevious?: string
}

export interface ExpertSlot {
  expertId: string
  overridePrompt?: string
  overrideTools?: string[]
}

export interface SkillSlot {
  skillName: string
  config: Record<string, unknown>
}

export interface MCPSlot {
  serverName: string
  toolFilter?: string[]
}

/** 工具完整定义（由 /api/workflows/tools 返回），包含用于渲染动态表单的 JSON Schema 参数 */
export interface ToolDef {
  name: string
  description: string
  parameters: {
    type: 'object'
    properties: Record<string, {
      type: string
      description?: string
      items?: { type: string }
      enum?: string[]
      default?: unknown
    }>
    required?: string[]
  }
  requiresApproval: boolean
  tags: string[]
}

export interface WorkflowExecutionConfig {
  autoApproveWrites: boolean
  maxIterations?: number
  timeoutSeconds?: number
}

export interface WorkflowVariable {
  name: string
  value: unknown
  type?: 'string' | 'number' | 'boolean' | 'array' | 'object'
}

export interface InputMapping {
  sourceNodeId: string
  sourcePort: string
  targetKey: string
}

export interface OutputExpose {
  key: string
  alias?: string
}

export type ConditionOperator =
  | 'eq'
  | 'ne'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'contains'
  | 'regex'

export interface ConditionRule {
  field?: string
  operator: ConditionOperator
  value: unknown
  branch?: string
}

export interface ConditionConfig {
  mode: 'expression' | 'simple' | 'prompt'
  expression?: string
  rules?: ConditionRule[]
  defaultBranch?: string
  fallbackBranch?: string
  /** @deprecated 旧 llm 模式迁移为 prompt 后使用 judgePrompt */
  naturalLanguage?: string
  judgePrompt?: string
  modelConfig?: ModelSlot
}

export interface DataContract {
  inputSchema: Record<string, string>
  outputSchema: Record<string, string>
  validate: boolean
}

export interface LoopConfig {
  mode: 'canvas'
  maxIterations: number
  bodyNodeIds: string[]
  bodyEdges: WorkflowEdge[]
}

export interface RetryConfig {
  maxRetries: number
  retryDelay: number
  backoffMultiplier?: number
  fallbackModel?: ModelSlot
  onRetryExhausted: 'skip' | 'error' | 'fallback'
}

export interface NodeRunContext {
  nodeId: string
  inputs: Record<string, unknown>
  outputs?: Record<string, unknown>
  tokensIn?: number
  tokensOut?: number
  elapsedMs?: number
  error?: string
  retryCount: number
}
