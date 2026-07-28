<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useI18n } from '@/i18n'
import { apiPath } from '@/utils/api'
import type { WorkflowNode, ModelSlot, PromptSlot, SkillSlot } from '@/types/workflow'
import ModelSelector from './ModelSelector.vue'

const props = defineProps<{
  node: WorkflowNode
}>()

const { t } = useI18n()
const workflowStore = useWorkflowStore()

const slots = computed(() => props.node.config.slots ?? {})

const model = computed<ModelSlot>({
  get: () =>
    (slots.value.model as ModelSlot) ?? { providerId: '', modelId: '' },
  set: (v) =>
    workflowStore.updateNodeConfig(props.node.id, {
      slots: { ...slots.value, model: v },
    }),
})

const prompt = computed<PromptSlot>({
  get: () =>
    (slots.value.prompt as PromptSlot) ?? { template: '{{input}}', version: 1 },
  set: (v) =>
    workflowStore.updateNodeConfig(props.node.id, {
      slots: { ...slots.value, prompt: v },
    }),
})

const maxToolIterations = computed({
  get: () => (props.node.config.maxToolIterations as number) ?? 10,
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { maxToolIterations: v }),
})

const toolLoopThreshold = computed({
  get: () => (props.node.config.toolLoopThreshold as number) ?? 3,
  set: (v) => workflowStore.updateNodeConfig(props.node.id, { toolLoopThreshold: v }),
})

// Skill management
interface SkillInfo { name: string; description: string; enabled: boolean }
const availableSkills = ref<SkillInfo[]>([])

async function loadSkills() {
  try {
    const res = await fetch(apiPath('/agent/skills'))
    const data = await res.json()
    if (data.ok && Array.isArray(data.skills)) {
      availableSkills.value = data.skills.map((s: any) => ({
        name: s.name,
        description: s.description ?? '',
        enabled: s.enabled ?? false,
      }))
    }
  } catch {
    // silent fallback
  }
}

onMounted(() => { loadSkills() })

const selectedSkills = computed<(SkillSlot | string)[]>({
  get: () => (slots.value.skills as (SkillSlot | string)[]) ?? [],
  set: (v) =>
    workflowStore.updateNodeConfig(props.node.id, {
      slots: { ...slots.value, skills: v },
    }),
})

function addSkill(skillName: string) {
  const current = selectedSkills.value as SkillSlot[]
  if (current.some((s) => (typeof s === 'string' ? s : s.skillName) === skillName)) return
  selectedSkills.value = [...current, { skillName, config: {} }]
}

function removeSkill(skillName: string) {
  const current = selectedSkills.value as SkillSlot[]
  selectedSkills.value = current.filter((s) =>
    (typeof s === 'string' ? s : s.skillName) !== skillName,
  )
}

function skillName(s: SkillSlot | string): string {
  return typeof s === 'string' ? s : s.skillName
}

const enabledSkills = computed(() =>
  availableSkills.value.filter((s) => s.enabled),
)

function updatePrompt(patch: Partial<PromptSlot>) {
  prompt.value = { ...prompt.value, ...patch }
}
</script>

<template>
  <div class="config-form">
    <h4 class="section-title">{{ t('workflow.config.model') }}</h4>

    <ModelSelector v-model="model" />

    <h4 class="section-title">{{ t('workflow.config.prompt') }}</h4>

    <label class="field-label">{{ t('workflow.config.systemPrompt') }}</label>
    <textarea
      :value="prompt.systemPrompt ?? ''"
      class="field-input"
      rows="3"
      @input="updatePrompt({ systemPrompt: ($event.target as HTMLTextAreaElement).value })"
    />

    <label class="field-label">{{ t('workflow.config.template') }}</label>
    <textarea
      :value="prompt.template"
      class="field-input"
      rows="5"
      @input="updatePrompt({ template: ($event.target as HTMLTextAreaElement).value })"
    />

    <h4 class="section-title">{{ t('workflow.config.skills') }}</h4>

    <div v-if="(selectedSkills as SkillSlot[]).length" class="skill-tags">
      <span
        v-for="s in (selectedSkills as SkillSlot[])"
        :key="skillName(s)"
        class="skill-tag"
      >
        {{ skillName(s) }}
        <button class="skill-tag-remove" @click="removeSkill(skillName(s))">×</button>
      </span>
    </div>
    <p v-else class="hint">{{ t('workflow.config.noSkills') }}</p>

    <select class="field-input" @change="addSkill(($event.target as HTMLSelectElement).value)">
      <option value="" disabled selected>{{ t('workflow.config.addSkill') }}</option>
      <option
        v-for="s in enabledSkills"
        :key="s.name"
        :value="s.name"
        :disabled="(selectedSkills as SkillSlot[]).some((x) => skillName(x) === s.name)"
      >
        {{ s.name }} — {{ s.description }}
      </option>
    </select>

    <h4 class="section-title">{{ t('workflow.config.toolCall') }}</h4>

    <label class="field-label">{{ t('workflow.config.maxToolIterations') }}</label>
    <input v-model.number="maxToolIterations" class="field-input" type="number" min="1" max="100" />

    <label class="field-label">{{ t('workflow.config.toolLoopThreshold') }}</label>
    <input v-model.number="toolLoopThreshold" class="field-input" type="number" min="2" max="20" />
  </div>
</template>

<style scoped>
.config-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-title {
  margin: 8px 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.field-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.field-input {
  padding: 8px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-size: 12px;
}

.hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 0;
}

.skill-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.skill-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
  font-size: 11px;
}

.skill-tag-remove {
  border: none;
  background: none;
  color: inherit;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  padding: 0;
}
</style>
