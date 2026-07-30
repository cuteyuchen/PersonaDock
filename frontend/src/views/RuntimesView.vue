<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { Radar } from 'lucide-vue-next'

import { api } from '@/api/client'
import type { RuntimeInstance } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

const queryClient = useQueryClient()
const { data, isPending, isError, error, refetch, isFetching } = useQuery({
  queryKey: ['runtimes'],
  queryFn: () => api.get<RuntimeInstance[]>('/api/instances'),
})
const { mutate, isPending: isDiscovering, error: discoverError } = useMutation({
  mutationFn: () => api.post('/api/v1/runtimes/discover', {}),
  onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: ['runtimes'] })
    await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    await queryClient.invalidateQueries({ queryKey: ['jobs'] })
  },
})

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
</script>

<template>
  <PageHeader eyebrow="Runtime Discovery" title="运行实例" description="查看 Hermes Profile 与 OpenClaw Agent/Workspace。接管向导迁移完成前继续从兼容界面进入。">
    <template #actions>
      <Button variant="outline" :disabled="isFetching" @click="refetch()">刷新</Button>
      <Button :disabled="isDiscovering" @click="mutate()">
        <Radar :class="isDiscovering ? 'animate-spin' : ''" />
        扫描运行实例
      </Button>
    </template>
  </PageHeader>

  <div v-if="discoverError" class="mb-4 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
    {{ discoverError instanceof Error ? discoverError.message : '扫描失败' }}
  </div>

  <Card>
    <CardContent class="p-0">
      <div v-if="isPending" class="p-8 text-sm text-muted-foreground">正在读取 Runtime Registry…</div>
      <div v-else-if="isError" class="p-8 text-sm text-red-700 dark:text-red-300">{{ error instanceof Error ? error.message : '加载失败' }}</div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[980px] text-left text-xs">
          <thead class="border-b bg-muted/45 text-muted-foreground"><tr><th class="px-4 py-2.5 font-medium">实例</th><th class="px-3 py-2.5 font-medium">Adapter</th><th class="px-3 py-2.5 font-medium">Transport</th><th class="px-3 py-2.5 font-medium">状态</th><th class="px-3 py-2.5 font-medium">位置</th><th class="px-3 py-2.5 font-medium">最后发现</th><th class="px-3 py-2.5"></th></tr></thead>
          <tbody>
            <tr v-for="instance in data ?? []" :key="instance.id" class="border-b last:border-0 hover:bg-muted/35">
              <td class="px-4 py-3"><div class="font-medium">{{ instance.display_name }}</div><div class="font-mono text-[10px] text-muted-foreground">{{ instance.platform_instance_id }}</div></td>
              <td class="px-3 py-3">{{ instance.adapter }}</td>
              <td class="px-3 py-3">{{ instance.transport }}</td>
              <td class="px-3 py-3"><StatusBadge :status="instance.managed ? 'managed' : 'unmanaged'" :label="instance.managed ? '已管理' : '未管理'" /></td>
              <td class="max-w-[420px] truncate px-3 py-3 font-mono text-[10px] text-muted-foreground">{{ instance.location }}</td>
              <td class="px-3 py-3 text-muted-foreground">{{ formatDate(instance.last_seen_at) }}</td>
              <td class="px-3 py-3 text-right"><a v-if="!instance.managed" href="/#/runtimes" class="font-medium hover:underline">接管预览</a><span v-else class="text-muted-foreground">—</span></td>
            </tr>
            <tr v-if="(data ?? []).length === 0"><td colspan="7" class="px-4 py-10 text-center text-muted-foreground">尚未发现运行实例</td></tr>
          </tbody>
        </table>
      </div>
    </CardContent>
  </Card>
</template>
