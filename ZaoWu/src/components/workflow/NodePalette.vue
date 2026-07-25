<script setup lang="ts">
import { Play, Bot, GitBranch, Hammer, RotateCcw, Workflow, Square, type LucideIcon } from '@lucide/vue'
import { useI18n } from '@/i18n'
import type { NodeType } from '@/types/workflow'

const { t } = useI18n()

interface PaletteItem {
  type: NodeType
  label: string
  icon: LucideIcon
  description: string
  defaultData: Record<string, unknown>
}

const items: PaletteItem[] = [
  {
    type: 'start',
    label: t('workflow.nodes.start'),
    icon: Play,
    description: t('workflow.nodes.startDesc'),
    defaultData: { label: t('workflow.nodes.start') },
  },
  {
    type: 'llm',
    label: t('workflow.nodes.llm'),
    icon: Bot,
    description: t('workflow.nodes.llmDesc'),
    defaultData: {
      label: t('workflow.nodes.llm'),
      config: {
        slots: {
          model: { providerId: '', modelId: '' },
          prompt: { template: '{{input}}', version: 1 },
        },
      },
    },
  },
  {
    type: 'condition',
    label: t('workflow.nodes.condition'),
    icon: GitBranch,
    description: t('workflow.nodes.conditionDesc'),
    defaultData: {
      label: t('workflow.nodes.condition'),
      config: {
        conditionConfig: { mode: 'simple', rules: [], defaultBranch: 'false' },
      },
    },
  },
  {
    type: 'tool',
    label: t('workflow.nodes.tool'),
    icon: Hammer,
    description: t('workflow.nodes.toolDesc'),
    defaultData: {
      label: t('workflow.nodes.tool'),
      config: { toolName: '', toolArgs: {} },
    },
  },
  {
    type: 'loop',
    label: t('workflow.nodes.loop'),
    icon: RotateCcw,
    description: t('workflow.nodes.loopDesc'),
    defaultData: {
      label: t('workflow.nodes.loop'),
      config: {
        loopConfig: { mode: 'for', maxIterations: 10, circuitBreakerAction: 'break', bodyNodeIds: [], bodyEdges: [] },
      },
    },
  },
  {
    type: 'router',
    label: t('workflow.nodes.router'),
    icon: Workflow,
    description: t('workflow.nodes.routerDesc'),
    defaultData: {
      label: t('workflow.nodes.router'),
      config: { routerMode: 'regex', routeCategories: [] },
    },
  },
  {
    type: 'end',
    label: t('workflow.nodes.end'),
    icon: Square,
    description: t('workflow.nodes.endDesc'),
    defaultData: { label: t('workflow.nodes.end'), config: { outputFormat: 'text' } },
  },
]

function onDragStart(event: DragEvent, item: PaletteItem) {
  if (!event.dataTransfer) return
  event.dataTransfer.setData(
    'application/json',
    JSON.stringify({ type: item.type, defaultData: item.defaultData })
  )
  event.dataTransfer.effectAllowed = 'copy'
}
</script>

<template>
  <aside class="node-palette">
    <h4 class="palette-title">{{ t('workflow.paletteTitle') }}</h4>
    <div
      v-for="item in items"
      :key="item.type"
      class="palette-item"
      draggable="true"
      @dragstart="(e) => onDragStart(e, item)"
    >
      <component :is="item.icon" class="palette-icon" :size="16" />
      <div class="palette-info">
        <span class="palette-label">{{ item.label }}</span>
        <span class="palette-desc">{{ item.description }}</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.node-palette {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 12px;
  background: var(--bg-secondary);
  overflow-y: auto;
}

.palette-title {
  margin: 0 0 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

.palette-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  margin-bottom: 8px;
  border-radius: 8px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-subtle);
  cursor: grab;
  transition: background 0.15s, border-color 0.15s;
}

.palette-item:hover {
  background: var(--bg-hover);
  border-color: var(--accent);
}

.palette-icon {
  flex-shrink: 0;
  color: var(--accent);
}

.palette-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.palette-label {
  font-size: 12px;
  font-weight: 500;
}

.palette-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
