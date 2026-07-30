<script setup lang="ts">
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { AlertTriangle, CheckCircle2, RefreshCw, RotateCcw, ServerCog } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { operationsApi, type JsonObject } from '@/api/operations'
import PageHeader from '@/components/PageHeader.vue'
import ResultPanel from '@/components/ResultPanel.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

const route = useRoute()
const queryClient = useQueryClient()
const mode = computed(() => String(route.meta.workspace ?? 'deployments'))
const busy = ref(false)
const error = ref<string | null>(null)
const result = ref<unknown>(null)

const personaId = ref('')
const runtimeId = ref(String(route.params.runtimeId ?? ''))
const adoptionName = ref('')
const adoptionDestination = ref('')
const linkExisting = ref(false)
const adoptionPreview = ref<JsonObject | null>(null)

const target = ref<'hermes' | 'openclaw'>('hermes')
const profile = ref('default')
const activate = ref(true)
const alias = ref(false)
const agent = ref('default')
const workspace = ref('')
const model = ref('')
const bindingsText = ref('')
const takeOwnership = ref(false)
const container = ref('')
const sshHost = ref('')
const deploymentPlan = ref<JsonObject | null>(null)
const confirmationToken = ref('')

const personasQuery = useQuery({ queryKey: ['personas'], queryFn: operationsApi.personas })
const runtimesQuery = useQuery({ queryKey: ['runtimes'], queryFn: operationsApi.runtimes })
const deploymentsQuery = useQuery({ queryKey: ['deployments'], queryFn: operationsApi.deployments })

watch(() => personasQuery.data.value?.items, (items) => {
  if (!personaId.value && items?.length) personaId.value = items[0].id
}, { immediate: true })
watch(() => route.params.runtimeId, (value) => { runtimeId.value = String(value ?? '') })

const currentRuntime = computed(() => runtimesQuery.data.value?.items.find((item) => item.id === runtimeId.value) ?? null)
const page = computed(() => mode.value === 'runtime'
  ? { eyebrow: 'Runtime Adoption', title: currentRuntime.value?.display_name || '运行实例详情', description: '检查发现信息，预览接管变更，并显式应用到 Registry。' }
  : { eyebrow: 'Native Deployment', title: '部署', description: '生成原生 Adapter 部署计划，审查语义变更后使用一次性令牌应用或回滚。' })

function text(value: unknown): string { return value instanceof Error ? value.message : String(value) }
function field(value: JsonObject | null, ...keys: string[]): string {
  for (const key of keys) {
    const found = value?.[key]
    if (typeof found === 'string') return found
  }
  return ''
}
function nested(value: JsonObject, key: string): JsonObject {
  const found = value[key]
  return typeof found === 'object' && found !== null && !Array.isArray(found) ? found as JsonObject : {}
}

async function run(operation: () => Promise<unknown>, invalidate: string[] = []): Promise<unknown> {
  busy.value = true
  error.value = null
  try {
    const value = await operation()
    result.value = value
    for (const key of invalidate) await queryClient.invalidateQueries({ queryKey: [key] })
    return value
  } catch (value) {
    error.value = text(value)
    return null
  } finally {
    busy.value = false
  }
}

async function previewAdoption(): Promise<void> {
  const value = await run(() => operationsApi.adoptionPreview(runtimeId.value, personaId.value || null, adoptionName.value || null, adoptionDestination.value || null, linkExisting.value))
  adoptionPreview.value = value as JsonObject | null
}

async function applyAdoption(): Promise<void> {
  await run(() => operationsApi.adopt(runtimeId.value, personaId.value || null, adoptionName.value || null, adoptionDestination.value || null, linkExisting.value), ['runtimes', 'personas'])
  adoptionPreview.value = null
}

async function createPlan(): Promise<void> {
  const payload: JsonObject = {
    target: target.value,
    persona_id: personaId.value,
    package_path: null,
    container: container.value || null,
    ssh_host: sshHost.value || null,
  }
  if (target.value === 'hermes') Object.assign(payload, { profile: profile.value || null, activate: activate.value, alias: alias.value })
  else Object.assign(payload, { agent: agent.value || null, workspace: workspace.value || null, model: model.value || null, bindings: bindingsText.value.split(',').map((item) => item.trim()).filter(Boolean), take_ownership: takeOwnership.value })
  const value = await run(() => operationsApi.createDeploymentPlan(payload), ['deployments'])
  deploymentPlan.value = value as JsonObject | null
  confirmationToken.value = field(deploymentPlan.value, 'confirmation_token', 'token')
}

async function applyPlan(): Promise<void> {
  const planId = field(deploymentPlan.value, 'plan_id', 'id')
  if (!planId || !confirmationToken.value) return
  await run(() => operationsApi.applyDeployment(planId, confirmationToken.value), ['deployments', 'runtimes'])
  confirmationToken.value = ''
  deploymentPlan.value = null
}

async function rollback(value: JsonObject): Promise<void> {
  const id = String(value.deployment_id ?? value.id ?? '')
  if (!id) return
  await run(() => operationsApi.rollbackDeployment(id), ['deployments', 'runtimes'])
}
</script>

<template>
  <PageHeader :eyebrow="page.eyebrow" :title="page.title" :description="page.description">
    <template #actions><Button variant="outline" :disabled="busy" @click="queryClient.invalidateQueries()"><RefreshCw class="size-4" />刷新</Button></template>
  </PageHeader>

  <div v-if="mode === 'runtime'" class="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_460px]">
    <div class="grid content-start gap-4">
      <Card>
        <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><ServerCog class="size-4" />实例信息</CardTitle></CardHeader>
        <CardContent v-if="currentRuntime" class="grid gap-3 text-xs md:grid-cols-2">
          <div><div class="text-muted-foreground">Adapter / Transport</div><div class="mt-1 font-medium">{{ currentRuntime.adapter }} / {{ currentRuntime.transport }}</div></div>
          <div><div class="text-muted-foreground">管理状态</div><Badge class="mt-1" :variant="currentRuntime.managed ? 'default' : 'secondary'">{{ currentRuntime.managed ? 'managed' : 'unmanaged' }}</Badge></div>
          <div class="md:col-span-2"><div class="text-muted-foreground">位置</div><div class="mt-1 break-all font-mono text-[11px]">{{ currentRuntime.location }}</div></div>
          <div><div class="text-muted-foreground">Platform ID</div><div class="mt-1 font-mono text-[11px]">{{ currentRuntime.platform_instance_id }}</div></div>
          <div><div class="text-muted-foreground">Last seen</div><div class="mt-1">{{ currentRuntime.last_seen_at }}</div></div>
          <pre class="max-h-64 overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-[10px] md:col-span-2">{{ JSON.stringify({ capabilities: currentRuntime.capabilities, metadata: currentRuntime.metadata }, null, 2) }}</pre>
        </CardContent>
        <CardContent v-else class="text-xs text-muted-foreground">未找到运行实例。</CardContent>
      </Card>

      <Card v-if="currentRuntime && !currentRuntime.managed">
        <CardHeader><CardTitle class="text-sm">接管计划</CardTitle></CardHeader>
        <CardContent class="grid gap-4">
          <div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">绑定已有 Persona（可选）</span><select v-model="personaId" class="h-9 rounded-md border bg-background px-3"><option value="">创建新 Persona</option><option v-for="item in personasQuery.data.value?.items ?? []" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label class="grid gap-1.5 text-xs"><span class="font-medium">新 Persona 名称</span><Input v-model="adoptionName" :disabled="!!personaId" /></label></div>
          <label class="grid gap-1.5 text-xs"><span class="font-medium">目标目录（可选）</span><Input v-model="adoptionDestination" placeholder="留空使用安全默认目录" /></label>
          <label class="flex items-center gap-2 text-xs"><input v-model="linkExisting" type="checkbox">只绑定已有工程，不复制运行时内容</label>
          <div class="flex gap-2"><Button variant="outline" :disabled="busy" @click="previewAdoption">预览接管</Button><Button :disabled="busy || !adoptionPreview" @click="applyAdoption">确认接管</Button></div>
        </CardContent>
      </Card>
      <ResultPanel :value="result" :error="error" @clear="result = null; error = null" />
    </div>
    <Card><CardHeader><CardTitle class="text-sm">接管预览</CardTitle></CardHeader><CardContent><pre class="max-h-[720px] overflow-auto whitespace-pre-wrap font-mono text-[11px]">{{ adoptionPreview ? JSON.stringify(adoptionPreview, null, 2) : '先生成预览，确认来源、目标和所有权变化。' }}</pre></CardContent></Card>
  </div>

  <div v-else class="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_520px]">
    <div class="grid content-start gap-4">
      <Card>
        <CardHeader><CardTitle class="text-sm">创建部署计划</CardTitle></CardHeader>
        <CardContent class="grid gap-4">
          <div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">Persona</span><select v-model="personaId" class="h-9 rounded-md border bg-background px-3"><option v-for="item in personasQuery.data.value?.items ?? []" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label class="grid gap-1.5 text-xs"><span class="font-medium">目标 Adapter</span><select v-model="target" class="h-9 rounded-md border bg-background px-3"><option value="hermes">Hermes Profile</option><option value="openclaw">OpenClaw Agent</option></select></label></div>
          <template v-if="target === 'hermes'"><div class="grid gap-3 md:grid-cols-3"><label class="grid gap-1.5 text-xs"><span class="font-medium">Profile</span><Input v-model="profile" /></label><label class="flex h-9 items-end gap-2 text-xs"><input v-model="activate" type="checkbox">激活 Profile</label><label class="flex h-9 items-end gap-2 text-xs"><input v-model="alias" type="checkbox">创建 Alias</label></div></template>
          <template v-else><div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">Agent</span><Input v-model="agent" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Workspace</span><Input v-model="workspace" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Model（可选）</span><Input v-model="model" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Bindings（逗号分隔）</span><Input v-model="bindingsText" /></label></div><label class="flex items-center gap-2 text-xs"><input v-model="takeOwnership" type="checkbox">接管已有 Agent/Workspace 所有权</label></template>
          <div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">Docker 容器（可选）</span><Input v-model="container" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">SSH Host（可选）</span><Input v-model="sshHost" /></label></div>
          <div v-if="container && sshHost" class="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200"><AlertTriangle class="mr-2 inline size-4" />Docker 与 SSH 不能同时使用。</div>
          <Button class="w-fit" :disabled="busy || !personaId || (!!container && !!sshHost)" @click="createPlan">生成 Plan</Button>
        </CardContent>
      </Card>

      <Card v-if="deploymentPlan">
        <CardHeader><CardTitle class="text-sm">Review → Apply</CardTitle></CardHeader>
        <CardContent class="grid gap-4"><div class="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">确认令牌仅显示一次，不会进入 Job。应用前后端会重新计算语义 Plan；若发生变化返回 409。</div><pre class="max-h-96 overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-[10px]">{{ JSON.stringify(deploymentPlan, null, 2) }}</pre><label class="grid gap-1.5 text-xs"><span class="font-medium">一次性确认令牌</span><Input v-model="confirmationToken" autocomplete="off" /></label><Button class="w-fit" :disabled="busy || !confirmationToken" @click="applyPlan"><CheckCircle2 class="size-4" />应用部署</Button></CardContent>
      </Card>
      <ResultPanel :value="result" :error="error" @clear="result = null; error = null" />
    </div>

    <Card>
      <CardHeader><CardTitle class="text-sm">部署历史</CardTitle></CardHeader>
      <CardContent class="grid gap-2">
        <div v-for="item in deploymentsQuery.data.value?.items ?? []" :key="String(item.deployment_id ?? item.id)" class="rounded-md border p-3 text-xs">
          <div class="flex items-center gap-2"><span class="font-mono text-[10px]">{{ String(item.deployment_id ?? item.id) }}</span><Badge class="ml-auto" variant="secondary">{{ String(item.status ?? item.state ?? 'unknown') }}</Badge></div>
          <div class="mt-2 text-muted-foreground">{{ String(nested(item, 'request').target ?? '') }} · {{ String(nested(item, 'request').persona_id ?? '') }}</div>
          <div class="mt-3 flex gap-2"><Button variant="outline" size="sm" @click="result = item">查看</Button><Button variant="destructive" size="sm" :disabled="busy" @click="rollback(item)"><RotateCcw class="size-3.5" />回滚</Button></div>
        </div>
        <div v-if="!deploymentsQuery.data.value?.items.length" class="rounded-md border border-dashed p-6 text-center text-xs text-muted-foreground">暂无部署记录</div>
      </CardContent>
    </Card>
  </div>
</template>
