<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'

import { api } from '@/api/client'
import type { JobRecord, ListResponse } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

const status = ref('')
const { data, isPending, isError, error, refetch, isFetching } = useQuery({
  queryKey: ['jobs'],
  queryFn: () => api.get<ListResponse<JobRecord>>('/api/v1/jobs?limit=200'),
  refetchInterval: 5_000,
})

const filtered = computed(() =>
  status.value ? (data.value?.items ?? []).filter((item) => item.status === status.value) : data.value?.items ?? [],
)

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date)
}
</script>

<template>
  <PageHeader eyebrow="Job Center" title="任务中心" description="查看构建、部署、治理和 AI 任务。页面每五秒刷新，任务输入仍只保存经过脱敏的摘要。">
    <template #actions><Button variant="outline" :disabled="isFetching" @click="refetch()">立即刷新</Button></template>
  </PageHeader>

  <Card>
    <CardContent class="p-0">
      <div class="flex items-center gap-3 border-b px-4 py-3">
        <label class="text-xs text-muted-foreground" for="job-status">状态</label>
        <select id="job-status" v-model="status" class="h-8 rounded-md border bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-ring">
          <option value="">全部</option>
          <option value="queued">queued</option>
          <option value="running">running</option>
          <option value="waiting-review">waiting-review</option>
          <option value="success">success</option>
          <option value="failed">failed</option>
          <option value="cancelled">cancelled</option>
        </select>
        <div class="ml-auto text-xs text-muted-foreground">{{ filtered.length }} / {{ data?.count ?? 0 }}</div>
      </div>

      <div v-if="isPending" class="p-8 text-sm text-muted-foreground">正在读取任务数据库…</div>
      <div v-else-if="isError" class="p-8 text-sm text-red-700 dark:text-red-300">{{ error instanceof Error ? error.message : '加载失败' }}</div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[1080px] text-left text-xs">
          <thead class="border-b bg-muted/45 text-muted-foreground"><tr><th class="px-4 py-2.5 font-medium">任务</th><th class="px-3 py-2.5 font-medium">状态</th><th class="px-3 py-2.5 font-medium">进度</th><th class="px-3 py-2.5 font-medium">Persona</th><th class="px-3 py-2.5 font-medium">创建</th><th class="px-3 py-2.5 font-medium">完成</th><th class="px-3 py-2.5 font-medium">错误</th></tr></thead>
          <tbody>
            <tr v-for="job in filtered" :key="job.id" class="border-b last:border-0 hover:bg-muted/35">
              <td class="px-4 py-3"><div class="font-medium">{{ job.label }}</div><div class="font-mono text-[10px] text-muted-foreground">{{ job.kind }} · {{ job.id }}</div></td>
              <td class="px-3 py-3"><StatusBadge :status="job.status" /></td>
              <td class="w-40 px-3 py-3"><div class="h-1.5 overflow-hidden rounded-full bg-muted"><div class="h-full bg-foreground/65" :style="{ width: `${job.progress}%` }" /></div><div class="mt-1 text-[10px] text-muted-foreground">{{ job.progress }}%</div></td>
              <td class="px-3 py-3 font-mono text-[10px]">{{ job.persona_id || '—' }}</td>
              <td class="px-3 py-3 text-muted-foreground">{{ formatDate(job.created_at) }}</td>
              <td class="px-3 py-3 text-muted-foreground">{{ formatDate(job.finished_at) }}</td>
              <td class="max-w-[300px] truncate px-3 py-3 text-red-700 dark:text-red-300">{{ job.error || '—' }}</td>
            </tr>
            <tr v-if="filtered.length === 0"><td colspan="7" class="px-4 py-10 text-center text-muted-foreground">没有匹配的任务记录</td></tr>
          </tbody>
        </table>
      </div>
    </CardContent>
  </Card>
</template>
