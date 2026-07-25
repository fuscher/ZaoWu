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
  | 'router'
  | 'loop'
  | 'end'

export type EdgeType = 'data' | 'condition' | 'break' | 'continue'

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
  condition?: ConditionDef
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
  routerMode?: 'semantic' | 'regex' | 'code'
  routeCategories?: RouteCategory[]
  outputFormat?: 'text' | 'json' | 'markdown'
  // Start 节点默认值（UI 配置使用）
  defaultValue?: string
}

export interface ModelSlot {
  providerId: string
  modelId: string
  temperature?: number
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
  mode: 'code' | 'simple' | 'llm'
  expression?: string
  rules?: ConditionRule[]
  defaultBranch?: string
  fallbackBranch?: string
  naturalLanguage?: string
}

export interface RouteCategory {
  id: string
  name: string
  condition: ConditionDef
}

export interface ConditionDef {
  mode: 'code' | 'llm_semantic'
  expression?: string
  naturalLanguage?: string
  embeddingThreshold?: number
}

export interface DataContract {
  inputSchema: Record<string, string>
  outputSchema: Record<string, string>
  validate: boolean
}

export interface LoopConfig {
  mode: 'for' | 'while'
  iterateOver?: string
  condition?: string
  maxIterations: number
  semanticSimilarityThreshold?: number
  circuitBreakerAction: 'break' | 'error'
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
