<script setup lang="ts">
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { Bot, CheckCircle2, KeyRound, RefreshCw, Settings2, Sparkles, Trash2 } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { operationsApi, type GenerationRecord, type JsonObject, type ProviderRecord } from '@/api/operations'
import PageHeader from '@/components/PageHeader.vue'
import ResultPanel from '@/components/ResultPanel.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

const route = useRoute()
const queryClient = useQueryClient()
const providersOnly = computed(() => String(route.meta.workspace ?? 'ai-studio') === 'providers')
const busy = ref(false)
const error = ref<string | null>(null)
const result = ref<unknown>(null)

const providerId = ref('')
const providerName = ref('Local provider')
const providerKind = ref('openai-compatible')
const providerBaseUrl = ref('http://127.0.0.1:11434/v1')
const providerModel = ref('')
const providerApiKey = ref('')
const temperature = ref(0.4)
const maxTokens = ref(4096)
const timeout = ref(90)
const structuredOutput = ref(true)
const modelOptions = ref<string[]>([])

const mode = ref('create')
const instruction = ref('')
const evidence = ref('')
const personaId = ref('')
const requestedPersonaId = ref('')
const requestedName = ref('')
const locale = ref('zh-CN')
const selectedGenerationId = ref('')
const selectedGeneration = ref<GenerationRecord | null>(null)
const applyFolder = ref('')

const providersQuery = useQuery({ queryKey: ['ai-providers'], queryFn: operationsApi.providers })
const generationsQuery = useQuery({ queryKey: ['ai-generations'], queryFn: operationsApi.generations })
const personasQuery = useQuery({ queryKey: ['personas'], queryFn: operationsApi.personas })

watch(() => providersQuery.data.value?.items, (values) => {
  if (!providerId.value && values?.length) providerId.value = values[0].id
}, { immediate: true })
watch(() => selectedGenerationId.value, async (value) => {
  if (!value) { selectedGeneration.value = null; return }
  selectedGeneration.value = await operationsApi.generation(value)
})

const page = computed(() => providersOnly.value
  ? { eyebrow: 'Encrypted Secret Vault', title: 'AI Provider 设置', description: '管理 Provider 元数据和加密 Secret。API Key 只发送到本地控制面，不会从 API 返回。' }
  : { eyebrow: 'AI Persona Studio', title: 'AI 人格工作室', description: '生成、蒸馏、混合或精炼 Persona 草稿；审查 Canonical、Diff、测试和编译结果后再 APPLY。' })

function message(value: unknown): string { return value instanceof Error ? value.message : String(value) }
function generationId(value: JsonObject): string { return String(value.id ?? value.generation_id ?? '') }
function providerLabel(value: ProviderRecord): string { return `${value.name} · ${value.kind} · ${value.model}` }

async function run(operation: () => Promise<unknown>, invalidate: string[] = []): Promise<unknown> {
  busy.value = true
  error.value = null
  try {
    const value = await operation()
    result.value = value
    for (const key of invalidate) await queryClient.invalidateQueries({ queryKey: [key] })
    return value
  } catch (value) {
    error.value = message(value)
    return null
  } finally {
    busy.value = false
  }
}

async function createProvider(): Promise<void> {
  const value = await run(() => operationsApi.createProvider({
    name: providerName.value,
    kind: providerKind.value,
    base_url: providerBaseUrl.value || null,
    model: providerModel.value,
    temperature: temperature.value,
    max_output_tokens: maxTokens.value,
    timeout_seconds: timeout.value,
    structured_output: structuredOutput.value,
    api_key: providerApiKey.value || null,
    headers: {},
  }), ['ai-providers'])
  providerApiKey.value = ''
  if (value && typeof value === 'object' && 'id' in value) providerId.value = String((value as JsonObject).id)
}

async function testProvider(value = providerId.value): Promise<void> {
  if (!value) return
  await run(() => operationsApi.testProvider(value))
}

async function listModels(): Promise<void> {
  if (!providerId.value) return
  const value = await run(() => operationsApi.providerModels(providerId.value)) as { items?: string[] } | null
  modelOptions.value = value?.items ?? []
}

async function removeProvider(value: ProviderRecord): Promise<void> {
  if (!window.confirm(`删除 Provider ${value.name}？加密 Secret 引用也会移除。`)) return
  await run(() => operationsApi.deleteProvider(value.id), ['ai-providers'])
  if (providerId.value === value.id) providerId.value = ''
}

async function generate(): Promise<void> {
  const payload: JsonObject = {
    provider_id: providerId.value,
    mode: mode.value,
    instruction: instruction.value,
    evidence: evidence.value,
    persona_id: mode.value === 'refine' ? personaId.value || null : null,
    requested_persona_id: mode.value === 'refine' ? null : requestedPersonaId.value || null,
    requested_name: mode.value === 'refine' ? null : requestedName.value || null,
    locale: locale.value,
  }
  const value = await run(() => operationsApi.createGeneration(payload), ['ai-generations']) as JsonObject | null
  const generated = value && typeof value.result === 'object' ? value.result as JsonObject : null
  const id = generated ? generationId(generated) : ''
  if (id) {
    selectedGenerationId.value = id
    selectedGeneration.value = generated as GenerationRecord
  }
  await queryClient.invalidateQueries({ queryKey: ['jobs'] })
}

async function selectGeneration(value: GenerationRecord): Promise<void> {
  selectedGenerationId.value = value.id
  selectedGeneration.value = await operationsApi.generation(value.id)
  result.value = selectedGeneration.value
}

async function applyGeneration(): Promise<void> {
  if (!selectedGenerationId.value) return
  await run(() => operationsApi.applyGeneration(selectedGenerationId.value, applyFolder.value || null), ['ai-generations', 'personas'])
  await queryClient.invalidateQueries({ queryKey: ['jobs'] })
}
</script>

<template>
  <PageHeader :eyebrow="page.eyebrow" :title="page.title" :description="page.description">
    <template #actions><Button variant="outline" :disabled="busy" @click="queryClient.invalidateQueries()"><RefreshCw class="size-4" />刷新</Button></template>
  </PageHeader>

  <div v-if="providersOnly" class="grid gap-4 2xl:grid-cols-[minmax(0,760px)_minmax(420px,1fr)]">
    <Card>
      <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><Settings2 class="size-4" />新增 Provider</CardTitle></CardHeader>
      <CardContent class="grid gap-4">
        <div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">名称</span><Input v-model="providerName" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">类型</span><select v-model="providerKind" class="h-9 rounded-md border bg-background px-3"><option v-for="value in ['openai','openai-compatible','anthropic','gemini','ollama']" :key="value">{{ value }}</option></select></label></div>
        <label class="grid gap-1.5 text-xs"><span class="font-medium">Base URL</span><Input v-model="providerBaseUrl" placeholder="官方 Provider 可留空" /></label>
        <div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">默认 Model</span><Input v-model="providerModel" list="provider-models" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">API Key / Secret</span><Input v-model="providerApiKey" type="password" autocomplete="new-password" /></label></div>
        <datalist id="provider-models"><option v-for="value in modelOptions" :key="value" :value="value" /></datalist>
        <div class="grid gap-3 md:grid-cols-3"><label class="grid gap-1.5 text-xs"><span class="font-medium">Temperature</span><Input v-model="temperature" type="number" min="0" max="2" step="0.1" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Max tokens</span><Input v-model="maxTokens" type="number" min="64" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Timeout 秒</span><Input v-model="timeout" type="number" min="1" max="600" /></label></div>
        <label class="flex items-center gap-2 text-xs"><input v-model="structuredOutput" type="checkbox">优先请求结构化输出</label>
        <div class="flex gap-2"><Button :disabled="busy || !providerName || !providerModel" @click="createProvider"><KeyRound class="size-4" />保存到加密 Vault</Button><Button variant="outline" :disabled="busy || !providerId" @click="listModels">读取模型列表</Button></div>
        <div class="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">Master Key 与 AES-256-GCM Vault 仅保存在 PersonaDock 本地状态目录。前端只显示 <code>has_secret</code>，不会回显 Secret。</div>
      </CardContent>
    </Card>

    <div class="grid content-start gap-4">
      <Card><CardHeader><CardTitle class="text-sm">已配置 Provider</CardTitle></CardHeader><CardContent class="grid gap-2"><article v-for="item in providersQuery.data.value?.items ?? []" :key="item.id" class="rounded-md border p-3 text-xs"><div class="flex items-center gap-2"><div class="font-medium">{{ item.name }}</div><Badge variant="secondary">{{ item.kind }}</Badge><Badge v-if="item.has_secret" class="ml-auto">Secret 已加密</Badge></div><div class="mt-1 font-mono text-[10px] text-muted-foreground">{{ item.model }} · {{ item.base_url || 'official endpoint' }}</div><div class="mt-3 flex gap-2"><Button size="sm" variant="outline" @click="providerId = item.id; testProvider(item.id)">测试</Button><Button size="sm" variant="outline" @click="providerId = item.id; listModels()">模型</Button><Button size="sm" variant="destructive" class="ml-auto" @click="removeProvider(item)"><Trash2 class="size-3.5" />删除</Button></div></article><div v-if="!providersQuery.data.value?.items.length" class="rounded-md border border-dashed p-8 text-center text-xs text-muted-foreground">尚未配置 Provider</div></CardContent></Card>
      <ResultPanel :value="result" :error="error" @clear="result = null; error = null" />
    </div>
  </div>

  <div v-else class="grid gap-4 2xl:grid-cols-[minmax(0,760px)_minmax(520px,1fr)]">
    <div class="grid content-start gap-4">
      <Card>
        <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><Sparkles class="size-4" />生成请求</CardTitle></CardHeader>
        <CardContent class="grid gap-4">
          <div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">Provider</span><select v-model="providerId" class="h-9 rounded-md border bg-background px-3"><option value="">选择 Provider</option><option v-for="item in providersQuery.data.value?.items ?? []" :key="item.id" :value="item.id">{{ providerLabel(item) }}</option></select></label><label class="grid gap-1.5 text-xs"><span class="font-medium">模式</span><select v-model="mode" class="h-9 rounded-md border bg-background px-3"><option value="create">Create</option><option value="distill">Distill</option><option value="hybrid">Hybrid</option><option value="refine">Refine</option></select></label></div>
          <template v-if="mode === 'refine'"><label class="grid gap-1.5 text-xs"><span class="font-medium">现有 Persona</span><select v-model="personaId" class="h-9 rounded-md border bg-background px-3"><option value="">选择 Persona</option><option v-for="item in personasQuery.data.value?.items ?? []" :key="item.id" :value="item.id">{{ item.name }} · {{ item.id }}</option></select></label></template>
          <template v-else><div class="grid gap-3 md:grid-cols-3"><label class="grid gap-1.5 text-xs"><span class="font-medium">新 Persona ID</span><Input v-model="requestedPersonaId" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">名称</span><Input v-model="requestedName" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Locale</span><Input v-model="locale" /></label></div></template>
          <label class="grid gap-1.5 text-xs"><span class="font-medium">指令</span><Textarea v-model="instruction" rows="7" placeholder="描述人格、行为、边界和输出目标" /></label>
          <label class="grid gap-1.5 text-xs"><span class="font-medium">证据 / 素材（可选）</span><Textarea v-model="evidence" rows="8" placeholder="可粘贴访谈、设定或现有材料；原文不会写入 Generation Store" /></label>
          <Button class="w-fit" :disabled="busy || !providerId || !instruction.trim() || (mode === 'refine' ? !personaId : !requestedPersonaId || !requestedName)" @click="generate"><Bot class="size-4" />生成审核草稿</Button>
          <div class="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">Job 只记录 Provider、模式、Persona 标识和输入哈希，不保存 instruction 或 evidence 原文。</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle class="text-sm">Generation 历史</CardTitle></CardHeader>
        <CardContent class="grid gap-2"><button v-for="item in generationsQuery.data.value?.items ?? []" :key="item.id" type="button" class="rounded-md border p-3 text-left text-xs hover:bg-muted/35" @click="selectGeneration(item)"><div class="flex items-center gap-2"><span class="font-mono text-[10px]">{{ item.id }}</span><Badge variant="secondary">{{ item.mode }}</Badge><span class="ml-auto text-muted-foreground">{{ item.status ?? '' }}</span></div><div class="mt-1 text-muted-foreground">{{ item.persona_id || item.requested_persona_id || 'new persona' }}</div></button><div v-if="!generationsQuery.data.value?.items.length" class="rounded-md border border-dashed p-8 text-center text-xs text-muted-foreground">暂无 Generation</div></CardContent>
      </Card>
      <ResultPanel :value="result" :error="error" @clear="result = null; error = null" />
    </div>

    <div class="grid content-start gap-4">
      <Card>
        <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><CheckCircle2 class="size-4" />Review → APPLY</CardTitle></CardHeader>
        <CardContent class="grid gap-4">
          <pre class="max-h-[720px] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-3 font-mono text-[10px]">{{ selectedGeneration ? JSON.stringify(selectedGeneration, null, 2) : '选择或生成一个草稿，审查 Canonical、semantic diff、risk、validation、tests 和 compile preview。' }}</pre>
          <label class="grid gap-1.5 text-xs"><span class="font-medium">新 Persona 目录（仅 Create/Distill/Hybrid）</span><Input v-model="applyFolder" placeholder="留空使用 requested Persona ID" /></label>
          <div class="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">APPLY 前请确认草稿未过期。Refine 的 base Revision 已变化时，后端会拒绝旧草稿。</div>
          <Button variant="destructive" :disabled="busy || !selectedGenerationId" @click="applyGeneration">输入语义确认：APPLY</Button>
        </CardContent>
      </Card>
      <Card><CardHeader><CardTitle class="text-sm">Provider 快捷操作</CardTitle></CardHeader><CardContent class="grid gap-3"><select v-model="providerId" class="h-9 rounded-md border bg-background px-3 text-xs"><option v-for="item in providersQuery.data.value?.items ?? []" :key="item.id" :value="item.id">{{ providerLabel(item) }}</option></select><div class="flex gap-2"><Button variant="outline" :disabled="!providerId" @click="testProvider()">测试连接</Button><Button variant="outline" :disabled="!providerId" @click="listModels">列出模型</Button><RouterLink to="/settings/providers" class="inline-flex h-9 items-center rounded-md border px-3 text-xs font-medium hover:bg-accent">管理 Provider</RouterLink></div></CardContent></Card>
    </div>
  </div>
</template>
