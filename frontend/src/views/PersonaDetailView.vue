<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { Braces, ExternalLink, Folder, GitBranch, Link2, ShieldCheck } from 'lucide-vue-next'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { personasApi } from '@/api/personas'
import PageHeader from '@/components/PageHeader.vue'
import PersonaTabs from '@/components/persona/PersonaTabs.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const route = useRoute()
const personaId = computed(() => String(route.params.personaId))
const query = useQuery({
  queryKey: computed(() => ['persona', personaId.value]),
  queryFn: () => personasApi.get(personaId.value),
})

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short', hour12: false }).format(date)
}
</script>

<template>
  <div v-if="query.isPending.value" class="py-16 text-center text-sm text-muted-foreground">正在读取 Persona…</div>
  <div v-else-if="query.isError.value" class="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
    {{ query.error.value instanceof Error ? query.error.value.message : '加载失败' }}
  </div>
  <template v-else-if="query.data.value">
    <PageHeader eyebrow="Persona Registry" :title="query.data.value.name" :description="query.data.value.summary || '该 Persona 尚未填写摘要。'">
      <template #actions>
        <Button as-child variant="outline"><RouterLink :to="`/personas/${encodeURIComponent(personaId)}/revisions`"><GitBranch class="size-4" />Revision</RouterLink></Button>
        <Button as-child><RouterLink :to="`/personas/${encodeURIComponent(personaId)}/editor`"><Braces class="size-4" />编辑 Canonical</RouterLink></Button>
      </template>
    </PageHeader>

    <PersonaTabs :persona-id="personaId" />

    <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div class="grid gap-4">
        <Card>
          <CardHeader><CardTitle class="text-sm">工程信息</CardTitle></CardHeader>
          <CardContent class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <div><div class="text-[11px] text-muted-foreground">Persona ID</div><div class="mt-1 font-mono text-xs">{{ query.data.value.id }}</div></div>
            <div><div class="text-[11px] text-muted-foreground">版本</div><div class="mt-1 text-sm font-medium">{{ query.data.value.version }}</div></div>
            <div><div class="text-[11px] text-muted-foreground">Canonical Schema</div><div class="mt-1"><Badge :variant="query.data.value.schema_version === 3 ? 'default' : 'destructive'">v{{ query.data.value.schema_version }}</Badge></div></div>
            <div class="sm:col-span-2 xl:col-span-3"><div class="text-[11px] text-muted-foreground">工程路径</div><div class="mt-1 flex items-start gap-2 rounded-md border bg-muted/35 p-3 font-mono text-[11px]"><Folder class="mt-0.5 size-3.5 shrink-0" /><span class="break-all">{{ query.data.value.source_path || '未绑定工程' }}</span></div></div>
            <div><div class="text-[11px] text-muted-foreground">创建时间</div><div class="mt-1 text-xs">{{ formatDate(query.data.value.created_at) }}</div></div>
            <div><div class="text-[11px] text-muted-foreground">更新时间</div><div class="mt-1 text-xs">{{ formatDate(query.data.value.updated_at) }}</div></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle class="text-sm">运行时绑定</CardTitle></CardHeader>
          <CardContent class="p-0">
            <div v-if="query.data.value.bindings.length === 0" class="p-6 text-xs text-muted-foreground">尚未绑定 Hermes Profile 或 OpenClaw Agent。</div>
            <table v-else class="w-full text-left text-xs">
              <thead class="border-b bg-muted/45 text-muted-foreground"><tr><th class="px-4 py-2.5 font-medium">Runtime ID</th><th class="px-3 py-2.5 font-medium">来源</th><th class="px-3 py-2.5 font-medium">部署版本</th><th class="px-3 py-2.5 font-medium">同步</th></tr></thead>
              <tbody><tr v-for="binding in query.data.value.bindings" :key="binding.id" class="border-b last:border-0"><td class="px-4 py-3 font-mono text-[10px]">{{ binding.runtime_instance_id }}</td><td class="px-3 py-3"><Badge variant="outline">{{ binding.adopted ? '接管' : '部署' }}</Badge></td><td class="px-3 py-3">{{ binding.last_deployed_version || '—' }}</td><td class="px-3 py-3 text-muted-foreground">{{ binding.last_synced_at ? formatDate(binding.last_synced_at) : '尚未同步' }}</td></tr></tbody>
            </table>
          </CardContent>
        </Card>
      </div>

      <div class="grid content-start gap-4">
        <Card>
          <CardHeader><CardTitle class="text-sm">状态与边界</CardTitle></CardHeader>
          <CardContent class="space-y-3 text-xs text-muted-foreground">
            <div class="flex gap-2"><ShieldCheck class="mt-0.5 size-4 shrink-0 text-emerald-600" /><p>Persona 工程是事实来源。保存、AI 应用、迁移和恢复均创建 Revision。</p></div>
            <div class="flex gap-2"><Link2 class="mt-0.5 size-4 shrink-0" /><p>当前绑定 {{ query.data.value.bindings.length }} 个运行实例；Runtime State、认证与原始 Session 不属于 Persona Definition。</p></div>
          </CardContent>
        </Card>
        <Card v-if="query.data.value.schema_version !== 3">
          <CardHeader><CardTitle class="text-sm text-amber-700 dark:text-amber-300">需要迁移</CardTitle></CardHeader>
          <CardContent class="space-y-3 text-xs text-muted-foreground">
            <p>该工程仍使用 Schema v{{ query.data.value.schema_version }}。Canonical 编辑器仅支持 v3，请先在“验证与测试”中预览迁移。</p>
            <Button as-child variant="outline" class="w-full"><RouterLink :to="`/personas/${encodeURIComponent(personaId)}/tests`">查看迁移计划<ExternalLink class="size-3.5" /></RouterLink></Button>
          </CardContent>
        </Card>
      </div>
    </div>
  </template>
</template>
