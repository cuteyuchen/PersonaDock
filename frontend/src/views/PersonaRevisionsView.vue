<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { GitCompareArrows, History, RotateCcw, ShieldAlert } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { personasApi } from '@/api/personas'
import type { PersonaDiff, RevisionRecord } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import PersonaTabs from '@/components/persona/PersonaTabs.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const route = useRoute()
const queryClient = useQueryClient()
const personaId = computed(() => String(route.params.personaId))
const beforeId = ref<string>('')
const afterId = ref<string>('current')
const diff = ref<PersonaDiff | null>(null)
const selectedRevision = ref<RevisionRecord | null>(null)
const restorePlan = ref<Record<string, unknown> | null>(null)
const restoreDiff = ref<PersonaDiff | null>(null)
const restoreSummary = ref('从历史 Revision 恢复')

const revisionsQuery = useQuery({
  queryKey: computed(() => ['persona-revisions', personaId.value]),
  queryFn: () => personasApi.revisions(personaId.value),
})
watch(() => revisionsQuery.data.value, (value) => {
  if (!value?.items.length || beforeId.value) return
  beforeId.value = value.items[0]?.parent_revision_id ?? value.items[0].revision_id
}, { immediate: true })

const diffMutation = useMutation({
  mutationFn: () => personasApi.diff(personaId.value, beforeId.value || null, afterId.value || null),
  onSuccess: (value) => { diff.value = value },
})
const previewMutation = useMutation({
  mutationFn: (revision: RevisionRecord) => personasApi.restorePreview(personaId.value, revision.revision_id),
  onSuccess: (value, revision) => {
    selectedRevision.value = revision
    restorePlan.value = value.plan
    restoreDiff.value = value.diff
  },
})
const restoreMutation = useMutation({
  mutationFn: async () => {
    const revision = selectedRevision.value
    const planHash = String(restorePlan.value?.plan_hash ?? '')
    if (!revision || !planHash) throw new Error('请先重新生成恢复预览')
    return personasApi.restore(personaId.value, revision.revision_id, planHash, restoreSummary.value)
  },
  onSuccess: async () => {
    restorePlan.value = null
    restoreDiff.value = null
    selectedRevision.value = null
    diff.value = null
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['persona-revisions', personaId.value] }),
      queryClient.invalidateQueries({ queryKey: ['persona-canonical', personaId.value] }),
      queryClient.invalidateQueries({ queryKey: ['persona', personaId.value] }),
      queryClient.invalidateQueries({ queryKey: ['personas'] }),
    ])
  },
})

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'medium', hour12: false }).format(date)
}
function riskVariant(level?: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (level === 'high' || level === 'destructive') return 'destructive'
  if (level === 'medium') return 'secondary'
  return 'outline'
}
</script>

<template>
  <PageHeader eyebrow="Revision Store" title="Revision 与 Diff" description="比较任意历史版本与当前工程；恢复前必须审核计划哈希和语义风险。" />
  <PersonaTabs :persona-id="personaId" />

  <Tabs default-value="history">
    <TabsList><TabsTrigger value="history"><History class="mr-1.5 size-3.5" />历史</TabsTrigger><TabsTrigger value="diff"><GitCompareArrows class="mr-1.5 size-3.5" />差异</TabsTrigger></TabsList>

    <TabsContent value="history">
      <Card>
        <CardContent class="p-0">
          <div v-if="revisionsQuery.isPending.value" class="p-8 text-xs text-muted-foreground">正在读取 Revision Store…</div>
          <div v-else-if="revisionsQuery.isError.value" class="p-8 text-xs text-red-700">{{ revisionsQuery.error.value instanceof Error ? revisionsQuery.error.value.message : '加载失败' }}</div>
          <div v-else class="overflow-x-auto">
            <table class="w-full min-w-[920px] text-left text-xs">
              <thead class="border-b bg-muted/45 text-muted-foreground"><tr><th class="px-4 py-2.5 font-medium">创建时间</th><th class="px-3 py-2.5 font-medium">来源</th><th class="px-3 py-2.5 font-medium">摘要</th><th class="px-3 py-2.5 font-medium">内容哈希</th><th class="px-3 py-2.5 font-medium">测试</th><th class="px-3 py-2.5"></th></tr></thead>
              <tbody>
                <tr v-for="revision in revisionsQuery.data.value?.items ?? []" :key="revision.revision_id" class="border-b last:border-0 hover:bg-muted/35">
                  <td class="px-4 py-3 text-muted-foreground">{{ formatDate(revision.created_at) }}</td>
                  <td class="px-3 py-3"><Badge variant="outline">{{ revision.source }}</Badge></td>
                  <td class="max-w-[360px] px-3 py-3"><div class="truncate font-medium">{{ revision.summary || '无摘要' }}</div><div class="mt-1 font-mono text-[9px] text-muted-foreground">{{ revision.revision_id }}</div></td>
                  <td class="px-3 py-3 font-mono text-[10px]">{{ revision.content_hash.slice(0, 16) }}</td>
                  <td class="px-3 py-3"><Badge :variant="revision.test_result?.ok === false ? 'destructive' : 'secondary'">{{ revision.test_result?.ok === false ? '失败' : '通过/未记录' }}</Badge></td>
                  <td class="px-3 py-3 text-right"><Button size="sm" variant="outline" :disabled="previewMutation.isPending.value" @click="previewMutation.mutate(revision)">恢复预览</Button></td>
                </tr>
                <tr v-if="(revisionsQuery.data.value?.items.length ?? 0) === 0"><td colspan="6" class="px-4 py-12 text-center text-muted-foreground">暂无 Revision</td></tr>
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </TabsContent>

    <TabsContent value="diff">
      <Card>
        <CardHeader><CardTitle class="text-sm">比较版本</CardTitle></CardHeader>
        <CardContent class="space-y-4">
          <div class="grid gap-3 lg:grid-cols-[1fr_1fr_auto]">
            <select v-model="beforeId" class="h-9 rounded-md border bg-background px-3 text-xs"><option value="current">当前工程</option><option v-for="revision in revisionsQuery.data.value?.items ?? []" :key="revision.revision_id" :value="revision.revision_id">{{ formatDate(revision.created_at) }} · {{ revision.summary || revision.source }}</option></select>
            <select v-model="afterId" class="h-9 rounded-md border bg-background px-3 text-xs"><option value="current">当前工程</option><option v-for="revision in revisionsQuery.data.value?.items ?? []" :key="revision.revision_id" :value="revision.revision_id">{{ formatDate(revision.created_at) }} · {{ revision.summary || revision.source }}</option></select>
            <Button :disabled="diffMutation.isPending.value" @click="diffMutation.mutate()"><GitCompareArrows class="size-4" />比较</Button>
          </div>
          <div v-if="diff" class="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
            <div class="rounded-md border p-4"><div class="text-xs font-medium">风险</div><Badge class="mt-2" :variant="riskVariant(diff.risk.level)">{{ diff.risk.level }}</Badge><ul class="mt-3 space-y-1 text-[11px] text-muted-foreground"><li v-for="reason in diff.risk.reasons" :key="reason">• {{ reason }}</li></ul></div>
            <pre class="max-h-[620px] overflow-auto rounded-md border bg-muted/35 p-4 text-[11px] leading-5">{{ JSON.stringify(diff, null, 2) }}</pre>
          </div>
        </CardContent>
      </Card>
    </TabsContent>
  </Tabs>

  <div v-if="restorePlan && selectedRevision" class="mt-4 grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
    <Card class="border-amber-300 dark:border-amber-900">
      <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><ShieldAlert class="size-4 text-amber-600" />恢复计划</CardTitle></CardHeader>
      <CardContent class="space-y-4 text-xs">
        <div><div class="text-muted-foreground">目标 Revision</div><div class="mt-1 font-mono text-[10px] break-all">{{ selectedRevision.revision_id }}</div></div>
        <div><div class="text-muted-foreground">计划哈希</div><div class="mt-1 font-mono text-[10px] break-all">{{ restorePlan.plan_hash }}</div></div>
        <div><div class="text-muted-foreground">风险</div><Badge class="mt-1" :variant="riskVariant(restoreDiff?.risk.level)">{{ restoreDiff?.risk.level }}</Badge></div>
        <Input v-model="restoreSummary" placeholder="恢复 Revision 摘要" />
        <div v-if="restoreMutation.isError.value" class="rounded-md border border-red-300 bg-red-50 p-3 text-red-800">{{ restoreMutation.error.value instanceof Error ? restoreMutation.error.value.message : '恢复失败' }}</div>
        <div class="flex gap-2"><Button variant="outline" class="flex-1" @click="restorePlan = null; selectedRevision = null">取消</Button><Button variant="destructive" class="flex-1" :disabled="restoreMutation.isPending.value" @click="restoreMutation.mutate()"><RotateCcw class="size-4" />确认恢复</Button></div>
      </CardContent>
    </Card>
    <Card><CardHeader><CardTitle class="text-sm">恢复语义 Diff</CardTitle></CardHeader><CardContent><pre class="max-h-[620px] overflow-auto rounded-md border bg-muted/35 p-4 text-[11px] leading-5">{{ JSON.stringify(restoreDiff, null, 2) }}</pre></CardContent></Card>
  </div>
</template>
