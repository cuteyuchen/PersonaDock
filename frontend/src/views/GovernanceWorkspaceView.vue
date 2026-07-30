<script setup lang="ts">
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { Check, Database, FileClock, RefreshCw, ShieldAlert, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { operationsApi, type JsonObject } from '@/api/operations'
import PageHeader from '@/components/PageHeader.vue'
import ResultPanel from '@/components/ResultPanel.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

const route = useRoute()
const queryClient = useQueryClient()
const mode = computed(() => String(route.meta.workspace ?? 'memory'))
const personaId = ref('')
const busy = ref(false)
const error = ref<string | null>(null)
const result = ref<unknown>(null)
const dashboard = ref<JsonObject | null>(null)
const policyText = ref('{}')
const plan = ref<JsonObject | null>(null)
const items = ref<JsonObject[]>([])
const conflicts = ref<JsonObject[]>([])
const history = ref<JsonObject[]>([])
const propagation = ref<JsonObject[]>([])
const includeDefinitions = ref(false)
const reviewScope = ref('shared')
const rejectReason = ref('不适合跨运行时传播')
const manualTitle = ref('Manual summary')
const manualSummary = ref('')
const manualTasks = ref('')
const manualSensitivity = ref('internal')

const personasQuery = useQuery({ queryKey: ['personas'], queryFn: operationsApi.personas })
watch(() => personasQuery.data.value?.items, (values) => {
  if (!personaId.value && values?.length) personaId.value = values[0].id
}, { immediate: true })
watch([personaId, mode], () => { if (personaId.value) void refreshAll() })

const page = computed(() => mode.value === 'sessions'
  ? { eyebrow: 'Reviewed Session Summaries', title: 'Session Summary', description: '只传播经过过滤、脱敏和审核的摘要，不同步原始 Session 或 Transcript。' }
  : { eyebrow: 'Governed Memory Sync', title: 'Memory 同步', description: '收集候选、审核敏感性、解决冲突、审查计划并显式应用到目标运行时。' })

function idOf(value: JsonObject): string { return String(value.id ?? value.item_id ?? value.summary_id ?? value.conflict_id ?? '') }
function statusOf(value: JsonObject): string { return String(value.status ?? 'unknown') }
function message(value: unknown): string { return value instanceof Error ? value.message : String(value) }
function display(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return '—'
  return JSON.stringify(value)
}

async function run(operation: () => Promise<unknown>): Promise<unknown> {
  busy.value = true
  error.value = null
  try {
    const value = await operation()
    result.value = value
    return value
  } catch (value) {
    error.value = message(value)
    return null
  } finally {
    busy.value = false
  }
}

async function refreshAll(): Promise<void> {
  if (!personaId.value) return
  busy.value = true
  error.value = null
  try {
    if (mode.value === 'sessions') {
      const [dash, policy, values, currentPlan] = await Promise.all([
        operationsApi.sessionDashboard(personaId.value),
        operationsApi.sessionPolicy(personaId.value),
        operationsApi.sessionItems(personaId.value),
        operationsApi.sessionPlan(personaId.value),
      ])
      dashboard.value = dash
      policyText.value = JSON.stringify(policy, null, 2)
      items.value = values
      plan.value = currentPlan
      conflicts.value = []
      history.value = []
      propagation.value = []
    } else {
      const [dash, policy, values, currentConflicts, currentPlan, runs, log] = await Promise.all([
        operationsApi.syncDashboard(personaId.value),
        operationsApi.syncPolicy(personaId.value),
        operationsApi.memoryItems(personaId.value),
        operationsApi.conflicts(personaId.value),
        operationsApi.syncPlan(personaId.value),
        operationsApi.syncRuns(personaId.value),
        operationsApi.propagation(personaId.value),
      ])
      dashboard.value = dash
      policyText.value = JSON.stringify(policy, null, 2)
      items.value = values
      conflicts.value = currentConflicts
      plan.value = currentPlan
      history.value = runs
      propagation.value = log
    }
  } catch (value) {
    error.value = message(value)
  } finally {
    busy.value = false
  }
}

async function collect(): Promise<void> {
  await run(() => mode.value === 'sessions' ? operationsApi.collectSessions(personaId.value) : operationsApi.collectMemory(personaId.value))
  await refreshAll()
  await queryClient.invalidateQueries({ queryKey: ['jobs'] })
}

async function savePolicy(): Promise<void> {
  try {
    const parsed = JSON.parse(policyText.value) as JsonObject
    await run(() => mode.value === 'sessions' ? operationsApi.updateSessionPolicy(personaId.value, parsed) : operationsApi.updateSyncPolicy(personaId.value, parsed))
    await refreshAll()
  } catch (value) {
    error.value = `Policy JSON 无效：${message(value)}`
  }
}

async function approve(item: JsonObject): Promise<void> {
  const id = idOf(item)
  if (!id) return
  await run(() => mode.value === 'sessions' ? operationsApi.approveSession(id, reviewScope.value) : operationsApi.approveMemory(id, reviewScope.value))
  await refreshAll()
}

async function reject(item: JsonObject): Promise<void> {
  const id = idOf(item)
  if (!id) return
  await run(() => mode.value === 'sessions' ? operationsApi.rejectSession(id, rejectReason.value) : operationsApi.rejectMemory(id, rejectReason.value))
  await refreshAll()
}

async function resolve(conflict: JsonObject, resolution: string): Promise<void> {
  const id = idOf(conflict)
  if (!id) return
  await run(() => operationsApi.resolveConflict(id, resolution))
  await refreshAll()
}

async function applyPlan(): Promise<void> {
  await run(() => mode.value === 'sessions' ? operationsApi.applySessions(personaId.value) : operationsApi.applyMemory(personaId.value, includeDefinitions.value))
  await refreshAll()
  await queryClient.invalidateQueries({ queryKey: ['jobs'] })
}

async function addManual(): Promise<void> {
  const tasks = manualTasks.value.split('\n').map((item) => item.trim()).filter(Boolean)
  await run(() => operationsApi.addManualSession(personaId.value, manualTitle.value, manualSummary.value, tasks, manualSensitivity.value))
  manualSummary.value = ''
  manualTasks.value = ''
  await refreshAll()
}
</script>

<template>
  <PageHeader :eyebrow="page.eyebrow" :title="page.title" :description="page.description">
    <template #actions>
      <select v-model="personaId" class="h-9 min-w-56 rounded-md border bg-background px-3 text-xs"><option v-for="item in personasQuery.data.value?.items ?? []" :key="item.id" :value="item.id">{{ item.name }} · {{ item.id }}</option></select>
      <Button variant="outline" :disabled="busy || !personaId" @click="refreshAll"><RefreshCw class="size-4" />刷新</Button>
      <Button :disabled="busy || !personaId" @click="collect">收集候选</Button>
    </template>
  </PageHeader>

  <div class="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_520px]">
    <div class="grid content-start gap-4">
      <Card>
        <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><component :is="mode === 'sessions' ? FileClock : Database" class="size-4" />审核队列</CardTitle></CardHeader>
        <CardContent class="grid gap-3">
          <div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">批准后的同步范围</span><select v-model="reviewScope" class="h-9 rounded-md border bg-background px-3"><option value="shared">shared</option><option value="local-only">local-only</option></select></label><label class="grid gap-1.5 text-xs"><span class="font-medium">拒绝理由</span><Input v-model="rejectReason" /></label></div>
          <article v-for="item in items" :key="idOf(item)" class="rounded-md border p-3 text-xs">
            <div class="flex items-start gap-2"><div class="min-w-0 flex-1"><div class="font-medium">{{ display(item.title ?? item.key ?? item.source_title ?? idOf(item)) }}</div><div class="mt-1 line-clamp-4 whitespace-pre-wrap text-muted-foreground">{{ display(item.summary ?? item.value ?? item.content ?? item.redacted_value) }}</div></div><Badge variant="secondary">{{ statusOf(item) }}</Badge></div>
            <div class="mt-2 flex flex-wrap gap-1 text-[10px] text-muted-foreground"><span>{{ display(item.sensitivity) }}</span><span>·</span><span>{{ display(item.source_adapter) }}</span><span>·</span><span>{{ display(item.sync_scope) }}</span></div>
            <div v-if="statusOf(item) === 'pending'" class="mt-3 flex gap-2"><Button size="sm" @click="approve(item)"><Check class="size-3.5" />批准</Button><Button size="sm" variant="destructive" @click="reject(item)"><X class="size-3.5" />拒绝</Button></div>
            <Button v-else size="sm" variant="outline" class="mt-3" @click="result = item">查看审计字段</Button>
          </article>
          <div v-if="!items.length" class="rounded-md border border-dashed p-8 text-center text-xs text-muted-foreground">没有候选项；先收集运行时内容或添加手工摘要。</div>
        </CardContent>
      </Card>

      <Card v-if="mode === 'memory' && conflicts.length">
        <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><ShieldAlert class="size-4 text-amber-600" />冲突</CardTitle></CardHeader>
        <CardContent class="grid gap-3"><article v-for="item in conflicts" :key="idOf(item)" class="rounded-md border border-amber-300 p-3 text-xs"><div class="font-medium">{{ display(item.key ?? item.fingerprint ?? idOf(item)) }}</div><pre class="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[10px]">{{ JSON.stringify(item, null, 2) }}</pre><div class="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="outline" @click="resolve(item, 'keep-existing')">保留现有</Button><Button size="sm" variant="outline" @click="resolve(item, 'replace')">替换</Button><Button size="sm" @click="resolve(item, 'keep-both')">保留两者</Button></div></article></CardContent>
      </Card>

      <Card v-if="mode === 'sessions'">
        <CardHeader><CardTitle class="text-sm">手工 Session Summary</CardTitle></CardHeader>
        <CardContent class="grid gap-3"><div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">标题</span><Input v-model="manualTitle" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">敏感性</span><select v-model="manualSensitivity" class="h-9 rounded-md border bg-background px-3"><option v-for="value in ['public','internal','private','restricted']" :key="value">{{ value }}</option></select></label></div><label class="grid gap-1.5 text-xs"><span class="font-medium">审核摘要</span><Textarea v-model="manualSummary" rows="6" placeholder="只写经过整理和脱敏的摘要" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">待办任务（每行一项）</span><Textarea v-model="manualTasks" rows="3" /></label><Button class="w-fit" :disabled="busy || !manualSummary.trim()" @click="addManual">加入审核队列</Button></CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle class="text-sm">Policy</CardTitle></CardHeader>
        <CardContent class="grid gap-3"><Textarea v-model="policyText" class="font-mono text-[11px]" rows="14" /><Button class="w-fit" variant="outline" :disabled="busy" @click="savePolicy">替换 Policy</Button></CardContent>
      </Card>
      <ResultPanel :value="result" :error="error" @clear="result = null; error = null" />
    </div>

    <div class="grid content-start gap-4">
      <Card>
        <CardHeader><CardTitle class="text-sm">Dashboard</CardTitle></CardHeader>
        <CardContent><pre class="max-h-72 overflow-auto whitespace-pre-wrap font-mono text-[10px]">{{ dashboard ? JSON.stringify(dashboard, null, 2) : '选择 Persona 后加载。' }}</pre></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle class="text-sm">传播计划</CardTitle></CardHeader>
        <CardContent class="grid gap-3"><pre class="max-h-[460px] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-3 font-mono text-[10px]">{{ plan ? JSON.stringify(plan, null, 2) : '暂无计划' }}</pre><label v-if="mode === 'memory'" class="flex items-center gap-2 text-xs"><input v-model="includeDefinitions" type="checkbox">包含 Memory Definitions</label><div class="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">Apply 会重新生成当前计划。只有审核通过且仍满足 Policy 的内容会传播。</div><Button variant="destructive" :disabled="busy || !plan" @click="applyPlan">显式确认并应用</Button></CardContent>
      </Card>
      <Card v-if="mode === 'memory'">
        <CardHeader><CardTitle class="text-sm">运行与传播历史</CardTitle></CardHeader>
        <CardContent class="grid gap-2"><button v-for="item in [...history, ...propagation]" :key="idOf(item) + JSON.stringify(item.created_at)" class="rounded-md border p-2 text-left text-[10px] hover:bg-muted/30" @click="result = item"><span class="font-mono">{{ idOf(item) || display(item.created_at) }}</span><span class="float-right">{{ statusOf(item) }}</span></button><div v-if="!history.length && !propagation.length" class="text-xs text-muted-foreground">暂无历史记录</div></CardContent>
      </Card>
    </div>
  </div>
</template>
