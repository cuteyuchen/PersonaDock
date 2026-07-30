<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { FolderSearch, Plus, Search } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { personasApi } from '@/api/personas'
import PageHeader from '@/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

const search = ref('')
const { data, isPending, isError, error, refetch, isFetching } = useQuery({
  queryKey: ['personas'],
  queryFn: personasApi.list,
})

const filtered = computed(() => {
  const needle = search.value.trim().toLowerCase()
  if (!needle) return data.value?.items ?? []
  return (data.value?.items ?? []).filter((item) =>
    [item.id, item.name, item.summary, item.source_path ?? ''].some((value) => value.toLowerCase().includes(needle)),
  )
})

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
</script>

<template>
  <PageHeader eyebrow="Persona Registry" title="人格" description="创建、注册和管理 Canonical Persona；详情、编辑、Revision、Diff 与测试均已迁移到 Vue。">
    <template #actions>
      <Button variant="outline" :disabled="isFetching" @click="refetch()">刷新</Button>
      <Button as-child variant="outline"><RouterLink to="/personas/register"><FolderSearch class="size-4" />注册工程</RouterLink></Button>
      <Button as-child><RouterLink to="/personas/new"><Plus class="size-4" />新建 Persona</RouterLink></Button>
    </template>
  </PageHeader>

  <Card>
    <CardContent class="p-0">
      <div class="flex items-center gap-3 border-b px-4 py-3">
        <div class="relative w-full max-w-md">
          <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input v-model="search" class="h-9 w-full rounded-md border bg-background pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-ring" placeholder="搜索名称、ID、摘要或工程路径" />
        </div>
        <div class="ml-auto text-xs text-muted-foreground">{{ filtered.length }} / {{ data?.count ?? 0 }}</div>
      </div>

      <div v-if="isPending" class="p-8 text-sm text-muted-foreground">正在读取 Persona Registry…</div>
      <div v-else-if="isError" class="p-8 text-sm text-red-700 dark:text-red-300">{{ error instanceof Error ? error.message : '加载失败' }}</div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[980px] text-left text-xs">
          <thead class="border-b bg-muted/45 text-muted-foreground"><tr><th class="px-4 py-2.5 font-medium">人格</th><th class="px-3 py-2.5 font-medium">版本</th><th class="px-3 py-2.5 font-medium">Schema</th><th class="px-3 py-2.5 font-medium">摘要</th><th class="px-3 py-2.5 font-medium">工程路径</th><th class="px-3 py-2.5 font-medium">更新时间</th><th class="px-3 py-2.5"></th></tr></thead>
          <tbody>
            <tr v-for="persona in filtered" :key="persona.id" class="border-b last:border-0 hover:bg-muted/35">
              <td class="px-4 py-3"><RouterLink :to="`/personas/${encodeURIComponent(persona.id)}`" class="font-medium hover:underline">{{ persona.name }}</RouterLink><div class="font-mono text-[10px] text-muted-foreground">{{ persona.id }}</div></td>
              <td class="px-3 py-3 tabular-nums">{{ persona.version }}</td>
              <td class="px-3 py-3">v{{ persona.schema_version }}</td>
              <td class="max-w-[320px] truncate px-3 py-3 text-muted-foreground">{{ persona.summary || '—' }}</td>
              <td class="max-w-[360px] truncate px-3 py-3 font-mono text-[10px] text-muted-foreground">{{ persona.source_path || '未绑定工程' }}</td>
              <td class="px-3 py-3 text-muted-foreground">{{ formatDate(persona.updated_at) }}</td>
              <td class="px-3 py-3 text-right"><RouterLink :to="`/personas/${encodeURIComponent(persona.id)}`" class="font-medium hover:underline">打开</RouterLink></td>
            </tr>
            <tr v-if="filtered.length === 0"><td colspan="7" class="px-4 py-10 text-center text-muted-foreground">没有匹配的 Persona</td></tr>
          </tbody>
        </table>
      </div>
    </CardContent>
  </Card>
</template>
