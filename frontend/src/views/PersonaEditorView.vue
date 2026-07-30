<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { Braces, CheckCircle2, Code2, FileDiff, Save, TerminalSquare, TriangleAlert } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { personasApi } from '@/api/personas'
import type { CanonicalPersona, PersonaDiff, PersonaTestResult, ValidationResult } from '@/api/types'
import FormField from '@/components/FormField.vue'
import MonacoJsonEditor from '@/components/editor/MonacoJsonEditor.vue'
import PageHeader from '@/components/PageHeader.vue'
import PersonaTabs from '@/components/persona/PersonaTabs.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

const route = useRoute()
const queryClient = useQueryClient()
const personaId = computed(() => String(route.params.personaId))
const model = ref<CanonicalPersona | null>(null)
const contentHash = ref('')
const rawJson = ref('')
const rawError = ref('')
const revisionSummary = ref('手动更新 Canonical Persona')
const saveDiff = ref<PersonaDiff | null>(null)
const saveValidation = ref<ValidationResult | null>(null)
const saveTests = ref<PersonaTestResult | null>(null)

const canonicalQuery = useQuery({
  queryKey: computed(() => ['persona-canonical', personaId.value]),
  queryFn: () => personasApi.canonical(personaId.value),
  retry: false,
})
const compileQuery = useQuery({
  queryKey: computed(() => ['persona-compile', personaId.value]),
  queryFn: () => personasApi.compilePreview(personaId.value),
  retry: false,
})

watch(() => canonicalQuery.data.value, (value) => {
  if (!value) return
  model.value = structuredClone(value.model)
  contentHash.value = value.content_hash
  rawJson.value = JSON.stringify(value.model, null, 2)
}, { immediate: true })

function lines(value: string): string[] {
  return value.split('\n').map((item) => item.trim()).filter(Boolean)
}
function setArray(path: 'traits' | 'principles' | 'targets', value: string): void {
  if (!model.value) return
  if (path === 'traits') model.value.identity.core_traits = lines(value)
  else if (path === 'principles') model.value.voice.principles = lines(value)
  else model.value.targets = value.split(',').map((item) => item.trim()).filter(Boolean)
  syncRaw()
}
const traitsText = computed({ get: () => model.value?.identity.core_traits.join('\n') ?? '', set: (value: string) => setArray('traits', value) })
const principlesText = computed({ get: () => model.value?.voice.principles.join('\n') ?? '', set: (value: string) => setArray('principles', value) })
const targetsText = computed({ get: () => model.value?.targets.join(', ') ?? '', set: (value: string) => setArray('targets', value) })

function syncRaw(): void {
  if (model.value) rawJson.value = JSON.stringify(model.value, null, 2)
}
function applyRaw(): boolean {
  rawError.value = ''
  try {
    const parsed = JSON.parse(rawJson.value) as CanonicalPersona
    if (!parsed || parsed.schema_version !== 3 || parsed.id !== personaId.value) throw new Error('JSON 必须是当前 Persona 的 Canonical v3 模型，且 ID 不可修改')
    model.value = parsed
    rawJson.value = JSON.stringify(parsed, null, 2)
    return true
  } catch (error) {
    rawError.value = error instanceof Error ? error.message : 'JSON 解析失败'
    return false
  }
}

const saveMutation = useMutation({
  mutationFn: async () => {
    if (!model.value) throw new Error('Canonical 模型尚未加载')
    if (!applyRaw()) throw new Error(rawError.value)
    return personasApi.saveCanonical(personaId.value, model.value, contentHash.value, revisionSummary.value)
  },
  onSuccess: async (result) => {
    model.value = structuredClone(result.model)
    rawJson.value = JSON.stringify(result.model, null, 2)
    contentHash.value = result.revision.content_hash
    saveDiff.value = result.diff
    saveValidation.value = result.validation
    saveTests.value = result.tests
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['personas'] }),
      queryClient.invalidateQueries({ queryKey: ['persona', personaId.value] }),
      queryClient.invalidateQueries({ queryKey: ['persona-revisions', personaId.value] }),
      queryClient.invalidateQueries({ queryKey: ['persona-compile', personaId.value] }),
    ])
  },
})

function riskVariant(level?: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (level === 'high' || level === 'destructive') return 'destructive'
  if (level === 'medium') return 'secondary'
  return 'outline'
}
</script>

<template>
  <div v-if="canonicalQuery.isPending.value" class="py-16 text-center text-sm text-muted-foreground">正在读取 Canonical Persona…</div>
  <div v-else-if="canonicalQuery.isError.value" class="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
    <div class="flex gap-2"><TriangleAlert class="mt-0.5 size-4 shrink-0" /><div><strong>无法打开 Canonical v3 编辑器</strong><p class="mt-1 text-xs">{{ canonicalQuery.error.value instanceof Error ? canonicalQuery.error.value.message : '加载失败' }}</p><RouterLink :to="`/personas/${encodeURIComponent(personaId)}/tests`" class="mt-3 inline-block text-xs font-medium underline">前往验证与迁移</RouterLink></div></div>
  </div>
  <template v-else-if="model">
    <PageHeader eyebrow="Canonical Persona v3" :title="`编辑 ${model.name}`" description="结构化字段与原始 JSON 共用同一模型；保存前会校验、运行场景测试并创建 Revision。">
      <template #actions><Badge variant="outline" class="font-mono text-[10px]">{{ contentHash.slice(0, 12) }}</Badge><Button :disabled="saveMutation.isPending.value" @click="saveMutation.mutate()"><Save class="size-4" />{{ saveMutation.isPending.value ? '正在保存…' : '保存 Revision' }}</Button></template>
    </PageHeader>
    <PersonaTabs :persona-id="personaId" />

    <Tabs default-value="structured">
      <div class="mb-3 flex flex-wrap items-center gap-3">
        <TabsList><TabsTrigger value="structured"><Braces class="mr-1.5 size-3.5" />结构化</TabsTrigger><TabsTrigger value="json"><Code2 class="mr-1.5 size-3.5" />JSON</TabsTrigger><TabsTrigger value="compile"><TerminalSquare class="mr-1.5 size-3.5" />编译预览</TabsTrigger></TabsList>
        <div class="ml-auto flex min-w-[280px] items-center gap-2"><Input v-model="revisionSummary" aria-label="Revision 摘要" placeholder="Revision 摘要" /><Button variant="outline" size="sm" @click="syncRaw">同步 JSON</Button></div>
      </div>

      <TabsContent value="structured">
        <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <Card>
            <CardContent class="grid gap-5 p-5">
              <div class="grid gap-4 md:grid-cols-3">
                <FormField label="名称"><Input v-model="model.name" @change="syncRaw" /></FormField>
                <FormField label="版本"><Input v-model="model.version" class="font-mono" @change="syncRaw" /></FormField>
                <FormField label="Locale"><Input v-model="model.locale" class="font-mono" @change="syncRaw" /></FormField>
              </div>
              <FormField label="摘要"><Textarea v-model="model.summary" :rows="3" @change="syncRaw" /></FormField>
              <FormField label="身份陈述"><Textarea v-model="model.identity.statement" :rows="5" @change="syncRaw" /></FormField>
              <div class="grid gap-4 md:grid-cols-2">
                <FormField label="核心特质" description="每行一个特质，保存时自动去重。"><Textarea v-model="traitsText" :rows="7" /></FormField>
                <FormField label="表达原则" description="每行一条原则。"><Textarea v-model="principlesText" :rows="7" /></FormField>
              </div>
              <FormField label="表达风格"><Textarea v-model="model.voice.style" :rows="4" @change="syncRaw" /></FormField>
              <div class="grid gap-4 md:grid-cols-3">
                <FormField label="目标字符数"><Input v-model="model.budgets.target_chars" type="number" @change="syncRaw" /></FormField>
                <FormField label="硬限制字符数"><Input v-model="model.budgets.hard_limit_chars" type="number" @change="syncRaw" /></FormField>
                <FormField label="编译目标"><Input v-model="targetsText" placeholder="hermes, openclaw, generic" /></FormField>
              </div>
            </CardContent>
          </Card>
          <div class="grid content-start gap-4">
            <Card><CardHeader><CardTitle class="text-sm">复杂规则</CardTitle></CardHeader><CardContent class="space-y-3 text-xs text-muted-foreground"><p>Boundary：<strong class="text-foreground">{{ model.boundaries.length }}</strong></p><p>Behavior：<strong class="text-foreground">{{ model.behaviors.length }}</strong></p><p>Boundary、Behavior 与 Memory Policy 保留完整结构，请在 JSON 视图中修改。保存后会按 Canonical 规则正规化 ID、优先级和来源。</p></CardContent></Card>
            <Card><CardHeader><CardTitle class="text-sm">并发保护</CardTitle></CardHeader><CardContent class="text-xs text-muted-foreground">编辑器保存时携带加载时的内容哈希。检测到工程已变化时会拒绝旧草稿，并要求重新加载后审查差异。</CardContent></Card>
          </div>
        </div>
      </TabsContent>

      <TabsContent value="json">
        <div class="mb-2 flex items-center justify-between"><div class="text-xs text-muted-foreground">直接编辑完整 Canonical v3 JSON。应用 JSON 只更新当前草稿，不会写入磁盘。</div><Button variant="outline" size="sm" @click="applyRaw">应用 JSON 到结构化模型</Button></div>
        <MonacoJsonEditor v-model="rawJson" />
        <div v-if="rawError" class="mt-2 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">{{ rawError }}</div>
      </TabsContent>

      <TabsContent value="compile">
        <div v-if="compileQuery.isPending.value" class="py-12 text-center text-xs text-muted-foreground">正在编译当前已保存版本…</div>
        <div v-else-if="compileQuery.data.value" class="grid gap-4 xl:grid-cols-2">
          <Card><CardHeader><CardTitle class="flex items-center justify-between text-sm"><span>SOUL</span><Badge :variant="compileQuery.data.value.soul_chars > (compileQuery.data.value.hard_limit_chars ?? Infinity) ? 'destructive' : 'outline'">{{ compileQuery.data.value.soul_chars }} 字符</Badge></CardTitle></CardHeader><CardContent><pre class="max-h-[600px] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/35 p-4 text-xs leading-5">{{ compileQuery.data.value.soul }}</pre></CardContent></Card>
          <Card><CardHeader><CardTitle class="text-sm">Persona Skill</CardTitle></CardHeader><CardContent><pre class="max-h-[600px] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/35 p-4 text-xs leading-5">{{ compileQuery.data.value.skill || '未生成 Skill 内容' }}</pre></CardContent></Card>
        </div>
      </TabsContent>
    </Tabs>

    <div v-if="saveMutation.isError.value" class="mt-4 rounded-md border border-red-300 bg-red-50 p-4 text-xs text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">{{ saveMutation.error.value instanceof Error ? saveMutation.error.value.message : '保存失败' }}</div>
    <div v-if="saveDiff" class="mt-4 grid gap-4 lg:grid-cols-3">
      <Card><CardContent class="flex gap-3 p-4"><FileDiff class="size-4 shrink-0" /><div><div class="text-xs font-medium">语义 Diff</div><Badge class="mt-2" :variant="riskVariant(saveDiff.risk.level)">{{ saveDiff.risk.level }}</Badge><p class="mt-2 text-[11px] text-muted-foreground">{{ saveDiff.risk.reasons.join('；') }}</p></div></CardContent></Card>
      <Card><CardContent class="flex gap-3 p-4"><CheckCircle2 class="size-4 shrink-0" :class="saveValidation?.ok ? 'text-emerald-600' : 'text-red-600'" /><div><div class="text-xs font-medium">项目校验</div><p class="mt-2 text-[11px] text-muted-foreground">{{ saveValidation?.ok ? '通过' : saveValidation?.errors.join('；') }}</p></div></CardContent></Card>
      <Card><CardContent class="flex gap-3 p-4"><CheckCircle2 class="size-4 shrink-0" :class="saveTests?.ok ? 'text-emerald-600' : 'text-red-600'" /><div><div class="text-xs font-medium">场景测试</div><p class="mt-2 text-[11px] text-muted-foreground">{{ saveTests?.ok ? '全部通过' : '存在失败场景，请前往验证与测试查看。' }}</p></div></CardContent></Card>
    </div>
  </template>
</template>
