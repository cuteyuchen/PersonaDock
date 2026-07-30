<script setup lang="ts">
import { useMutation, useQuery } from '@tanstack/vue-query'
import { GitCompareArrows } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

import { personasApi } from '@/api/personas'
import type { PersonaDiff } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const personaId = ref('')
const beforeId = ref('')
const afterId = ref('current')
const diff = ref<PersonaDiff | null>(null)
const personasQuery = useQuery({ queryKey: ['personas'], queryFn: personasApi.list })
const revisionsQuery = useQuery({
  queryKey: computed(() => ['persona-revisions', personaId.value]),
  queryFn: () => personasApi.revisions(personaId.value),
  enabled: computed(() => Boolean(personaId.value)),
})
watch(() => personasQuery.data.value, (value) => {
  if (!personaId.value && value?.items.length) personaId.value = value.items[0].id
}, { immediate: true })
watch(personaId, () => {
  beforeId.value = ''
  afterId.value = 'current'
  diff.value = null
})
watch(() => revisionsQuery.data.value, (value) => {
  if (!beforeId.value && value?.items.length) beforeId.value = value.items[0].revision_id
}, { immediate: true })
const mutation = useMutation({
  mutationFn: () => personasApi.diff(personaId.value, beforeId.value || null, afterId.value || null),
  onSuccess: (value) => { diff.value = value },
})
function riskVariant(level?: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (level === 'high' || level === 'destructive') return 'destructive'
  if (level === 'medium') return 'secondary'
  return 'outline'
}
</script>

<template>
  <PageHeader eyebrow="Semantic Diff" title="差异中心" description="跨 Persona 选择 Revision，查看 Canonical 语义变化和风险，而不是只比较 YAML 文本。" />
  <Card>
    <CardHeader><CardTitle class="text-sm">比较范围</CardTitle></CardHeader>
    <CardContent class="space-y-4">
      <div class="grid gap-3 xl:grid-cols-[1fr_1fr_1fr_auto]">
        <select v-model="personaId" class="h-9 rounded-md border bg-background px-3 text-xs"><option value="" disabled>选择 Persona</option><option v-for="persona in personasQuery.data.value?.items ?? []" :key="persona.id" :value="persona.id">{{ persona.name }} · {{ persona.id }}</option></select>
        <select v-model="beforeId" class="h-9 rounded-md border bg-background px-3 text-xs"><option value="current">当前工程</option><option v-for="revision in revisionsQuery.data.value?.items ?? []" :key="revision.revision_id" :value="revision.revision_id">{{ revision.summary || revision.source }} · {{ revision.content_hash.slice(0, 10) }}</option></select>
        <select v-model="afterId" class="h-9 rounded-md border bg-background px-3 text-xs"><option value="current">当前工程</option><option v-for="revision in revisionsQuery.data.value?.items ?? []" :key="revision.revision_id" :value="revision.revision_id">{{ revision.summary || revision.source }} · {{ revision.content_hash.slice(0, 10) }}</option></select>
        <Button :disabled="!personaId || mutation.isPending.value" @click="mutation.mutate()"><GitCompareArrows class="size-4" />比较</Button>
      </div>
      <div v-if="mutation.isError.value" class="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800">{{ mutation.error.value instanceof Error ? mutation.error.value.message : '比较失败' }}</div>
    </CardContent>
  </Card>

  <div v-if="diff" class="mt-4 grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
    <Card><CardHeader><CardTitle class="text-sm">风险摘要</CardTitle></CardHeader><CardContent class="space-y-3"><Badge :variant="riskVariant(diff.risk.level)">{{ diff.risk.level }}</Badge><ul class="space-y-1 text-xs text-muted-foreground"><li v-for="reason in diff.risk.reasons" :key="reason">• {{ reason }}</li></ul><div class="border-t pt-3 font-mono text-[10px] text-muted-foreground"><div>before {{ diff.before_hash }}</div><div>after&nbsp; {{ diff.after_hash }}</div></div></CardContent></Card>
    <Card><CardHeader><CardTitle class="text-sm">语义变更</CardTitle></CardHeader><CardContent><pre class="max-h-[720px] overflow-auto rounded-md border bg-muted/35 p-4 text-[11px] leading-5">{{ JSON.stringify(diff, null, 2) }}</pre></CardContent></Card>
  </div>
</template>
