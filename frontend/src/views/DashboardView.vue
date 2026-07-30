<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ArrowRight, Radar } from 'lucide-vue-next'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import { api } from '@/api/client'
import type { DashboardResponse } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

const queryClient = useQueryClient()
const dashboardQuery = useQuery({
  queryKey: ['dashboard'],
  queryFn: () => api.get<DashboardResponse>('/api/v1/dashboard'),
})

const discoverMutation = useMutation({
  mutationFn: () => api.post('/api/v1/runtimes/discover', {}),
  onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    await queryClient.invalidateQueries({ queryKey: ['runtimes'] })
    await queryClient.invalidateQueries({ queryKey: ['jobs'] })
  },
})

const metrics = computed(() => dashboardQuery.data.value?.metrics)

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}
</script>

<template>
  <PageHeader
    eyebrow="Control Plane"
    title="本地人格控制面"
    description="集中查看 Persona、运行实例和待处理任务。写操作继续遵循审核、确认和可恢复原则。"
  >
    <template #actions>
      <Button variant="outline" :disabled="discoverMutation.isPending.value" @click="discoverMutation.mutate()">
        <Radar :class="discoverMutation.isPending.value ? 'animate-spin' : ''" />
        扫描运行实例
      </Button>
      <RouterLink to="/personas" class="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3.5 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        查看人格 <ArrowRight class="size-4" />
      </RouterLink>
    </template>
  </PageHeader>

  <div v-if="dashboardQuery.isPending.value" class="rounded-md border bg-card p-8 text-sm text-muted-foreground">正在读取本地 Registry…</div>
  <div v-else-if="dashboardQuery.isError.value" class="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
    {{ dashboardQuery.error.value instanceof Error ? dashboardQuery.error.value.message : '控制面数据加载失败' }}
  </div>
  <template v-else>
    <section class="mb-5 grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border md:grid-cols-3 xl:grid-cols-6">
      <div v-for="item in [
        ['Persona', metrics?.personas ?? 0, 'Registry 人格'],
        ['运行实例', metrics?.runtime_instances ?? 0, 'Hermes / OpenClaw'],
        ['已管理', metrics?.managed_instances ?? 0, '已绑定 Persona'],
        ['未管理', metrics?.unmanaged_instances ?? 0, '等待接管'],
        ['活动任务', metrics?.active_jobs ?? 0, '运行或待审核'],
        ['失败任务', metrics?.failed_jobs ?? 0, '需要处理'],
      ]" :key="String(item[0])" class="bg-card px-4 py-3">
        <div class="text-[11px] text-muted-foreground">{{ item[0] }}</div>
        <div class="mt-1 text-2xl font-semibold tabular-nums">{{ item[1] }}</div>
        <div class="mt-1 text-[11px] text-muted-foreground">{{ item[2] }}</div>
      </div>
    </section>

    <div class="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(340px,0.75fr)]">
      <div class="space-y-5">
        <Card>
          <CardHeader class="flex-row items-center justify-between">
            <div>
              <CardTitle>最近 Persona</CardTitle>
              <CardDescription>按 Registry 更新时间显示</CardDescription>
            </div>
            <RouterLink to="/personas" class="text-xs font-medium hover:underline">全部</RouterLink>
          </CardHeader>
          <CardContent class="overflow-x-auto p-0">
            <table class="w-full min-w-[760px] text-left text-xs">
              <thead class="border-b bg-muted/45 text-muted-foreground">
                <tr><th class="px-4 py-2.5 font-medium">人格</th><th class="px-3 py-2.5 font-medium">版本</th><th class="px-3 py-2.5 font-medium">Schema</th><th class="px-3 py-2.5 font-medium">摘要</th><th class="px-3 py-2.5 font-medium">更新时间</th></tr>
              </thead>
              <tbody>
                <tr v-for="persona in dashboardQuery.data.value?.personas ?? []" :key="persona.id" class="border-b last:border-0 hover:bg-muted/35">
                  <td class="px-4 py-3"><div class="font-medium">{{ persona.name }}</div><div class="font-mono text-[10px] text-muted-foreground">{{ persona.id }}</div></td>
                  <td class="px-3 py-3 tabular-nums">{{ persona.version }}</td>
                  <td class="px-3 py-3">v{{ persona.schema_version }}</td>
                  <td class="max-w-[340px] truncate px-3 py-3 text-muted-foreground">{{ persona.summary || '—' }}</td>
                  <td class="px-3 py-3 text-muted-foreground">{{ formatDate(persona.updated_at) }}</td>
                </tr>
                <tr v-if="!(dashboardQuery.data.value?.personas.length)"><td colspan="5" class="px-4 py-8 text-center text-muted-foreground">尚未注册 Persona</td></tr>
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader class="flex-row items-center justify-between">
            <div><CardTitle>运行实例</CardTitle><CardDescription>本地、Docker 和 SSH 发现结果</CardDescription></div>
            <RouterLink to="/runtimes" class="text-xs font-medium hover:underline">全部</RouterLink>
          </CardHeader>
          <CardContent class="overflow-x-auto p-0">
            <table class="w-full min-w-[720px] text-left text-xs">
              <thead class="border-b bg-muted/45 text-muted-foreground"><tr><th class="px-4 py-2.5 font-medium">实例</th><th class="px-3 py-2.5 font-medium">Adapter</th><th class="px-3 py-2.5 font-medium">传输</th><th class="px-3 py-2.5 font-medium">状态</th><th class="px-3 py-2.5 font-medium">位置</th></tr></thead>
              <tbody>
                <tr v-for="instance in dashboardQuery.data.value?.instances ?? []" :key="instance.id" class="border-b last:border-0 hover:bg-muted/35">
                  <td class="px-4 py-3"><div class="font-medium">{{ instance.display_name }}</div><div class="font-mono text-[10px] text-muted-foreground">{{ instance.platform_instance_id }}</div></td>
                  <td class="px-3 py-3">{{ instance.adapter }}</td>
                  <td class="px-3 py-3">{{ instance.transport }}</td>
                  <td class="px-3 py-3"><StatusBadge :status="instance.managed ? 'managed' : 'unmanaged'" :label="instance.managed ? '已管理' : '未管理'" /></td>
                  <td class="max-w-[360px] truncate px-3 py-3 font-mono text-[10px] text-muted-foreground">{{ instance.location }}</td>
                </tr>
                <tr v-if="!(dashboardQuery.data.value?.instances.length)"><td colspan="5" class="px-4 py-8 text-center text-muted-foreground">尚未发现运行实例</td></tr>
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>

      <Card class="h-fit">
        <CardHeader class="flex-row items-center justify-between">
          <div><CardTitle>最近任务</CardTitle><CardDescription>构建、部署、治理与 AI 操作</CardDescription></div>
          <RouterLink to="/jobs" class="text-xs font-medium hover:underline">全部</RouterLink>
        </CardHeader>
        <CardContent class="divide-y p-0">
          <div v-for="job in dashboardQuery.data.value?.jobs ?? []" :key="job.id" class="px-4 py-3">
            <div class="flex items-start justify-between gap-3"><div class="min-w-0"><div class="truncate text-xs font-medium">{{ job.label }}</div><div class="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">{{ job.kind }}</div></div><StatusBadge :status="job.status" /></div>
            <div class="mt-2 h-1 overflow-hidden rounded-full bg-muted"><div class="h-full bg-foreground/65" :style="{ width: `${job.progress}%` }" /></div>
            <div class="mt-1.5 flex justify-between text-[10px] text-muted-foreground"><span>{{ job.progress }}%</span><span>{{ formatDate(job.created_at) }}</span></div>
          </div>
          <div v-if="!(dashboardQuery.data.value?.jobs.length)" class="px-4 py-8 text-center text-xs text-muted-foreground">暂无任务记录</div>
        </CardContent>
      </Card>
    </div>
  </template>
</template>
