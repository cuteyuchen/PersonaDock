<script setup lang="ts">
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  ArchiveRestore,
  Bot,
  Database,
  GitCompareArrows,
  IdCard,
  KeyRound,
  LayoutDashboard,
  ListTodo,
  Menu,
  MessagesSquare,
  PackageCheck,
  PanelLeftClose,
  Plug,
  RefreshCw,
  Rocket,
  Server,
  Settings,
  UsersRound,
  X,
} from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import { api } from '@/api/client'
import type { MetaResponse } from '@/api/types'
import { Button } from '@/components/ui/button'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const route = useRoute()
const queryClient = useQueryClient()
const mobileOpen = ref(false)

const metaQuery = useQuery({
  queryKey: ['meta'],
  queryFn: () => api.get<MetaResponse>('/api/v1/meta'),
})

const groups = [
  {
    label: '控制',
    items: [
      ['overview', '概览', LayoutDashboard],
      ['personas', '人格', UsersRound],
      ['ai-studio', 'AI 人格工作室', Bot],
      ['diff', '差异中心', GitCompareArrows],
      ['runtimes', '运行实例', Server],
      ['deployments', '部署', Rocket],
    ],
  },
  {
    label: '治理',
    items: [
      ['memory', 'Memory 同步', Database],
      ['sessions', 'Session Summary', MessagesSquare],
      ['packages', 'PersonaPack 与信任', PackageCheck],
      ['backups', '备份', ArchiveRestore],
      ['character-cards', 'Character Card', IdCard],
    ],
  },
  {
    label: '系统',
    items: [
      ['adapters', 'Adapter 与 Skill', Plug],
      ['settings/providers', 'AI Provider 设置', KeyRound],
      ['jobs', '任务中心', ListTodo],
      ['settings', '系统设置', Settings],
    ],
  },
] as const

const title = computed(() => String(route.meta.title ?? '概览'))
const connectionLabel = computed(() => {
  if (metaQuery.isPending.value) return '正在连接'
  if (metaQuery.isError.value) return '连接失败'
  return `本地控制面 · API v${metaQuery.data.value?.api_version ?? 1}`
})

async function refresh(): Promise<void> {
  await queryClient.invalidateQueries()
}

watch(
  () => route.fullPath,
  () => {
    mobileOpen.value = false
  },
)

onMounted(() => session.applyTheme())
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <div v-if="mobileOpen" class="fixed inset-0 z-40 bg-black/35 lg:hidden" @click="mobileOpen = false" />

    <aside
      class="fixed inset-y-0 left-0 z-50 flex w-[248px] flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar)] text-[var(--sidebar-foreground)] transition-transform lg:translate-x-0"
      :class="mobileOpen ? 'translate-x-0' : '-translate-x-full'"
    >
      <div class="flex h-14 items-center gap-3 border-b border-[var(--sidebar-border)] px-4">
        <div class="grid size-8 place-items-center rounded-md border border-white/10 bg-white/5 text-xs font-semibold tracking-[0.18em]">PD</div>
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-semibold">PersonaDock</div>
          <div class="truncate text-[11px] text-zinc-400">
            Vue Control Plane {{ metaQuery.data.value?.web_control_plane ?? 2 }}
          </div>
        </div>
        <Button variant="ghost" size="icon" class="text-zinc-300 hover:bg-white/8 hover:text-white lg:hidden" @click="mobileOpen = false">
          <X />
        </Button>
      </div>

      <nav class="flex-1 overflow-y-auto px-2 py-3" aria-label="主导航">
        <div v-for="group in groups" :key="group.label" class="mb-4">
          <div class="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">{{ group.label }}</div>
          <RouterLink
            v-for="item in group.items"
            :key="item[0]"
            :to="`/${item[0]}`"
            class="mb-0.5 flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13px] text-zinc-300 transition-colors hover:bg-white/6 hover:text-white"
            active-class="bg-white/10 text-white"
          >
            <component :is="item[2]" class="size-4" />
            <span class="min-w-0 flex-1 truncate">{{ item[1] }}</span>
          </RouterLink>
        </div>
      </nav>

      <div class="border-t border-[var(--sidebar-border)] p-3">
        <a href="/legacy" class="flex items-center gap-2 rounded-md px-2 py-2 text-xs text-zinc-400 hover:bg-white/6 hover:text-zinc-100">
          <PanelLeftClose class="size-4" />
          旧界面兼容入口
        </a>
        <div class="px-2 pt-2 text-[10px] leading-4 text-zinc-600">本地优先 · Secret 不返回浏览器</div>
      </div>
    </aside>

    <div class="min-h-screen lg:pl-[248px]">
      <header class="sticky top-0 z-30 flex h-14 items-center border-b bg-background/95 px-3 backdrop-blur lg:px-5">
        <Button variant="ghost" size="icon" class="mr-2 lg:hidden" aria-label="打开导航" @click="mobileOpen = true">
          <Menu />
        </Button>
        <div class="min-w-0">
          <div class="text-[11px] text-muted-foreground">PersonaDock /</div>
          <h1 class="truncate text-sm font-semibold">{{ title }}</h1>
        </div>
        <div class="ml-auto flex items-center gap-2">
          <div class="hidden items-center gap-2 rounded-md border bg-card px-2.5 py-1.5 text-[11px] text-muted-foreground sm:flex">
            <span
              class="size-1.5 rounded-full"
              :class="metaQuery.isError.value ? 'bg-red-500' : metaQuery.isPending.value ? 'bg-amber-500' : 'bg-emerald-500'"
            />
            {{ connectionLabel }}
          </div>
          <Button variant="outline" size="icon" aria-label="刷新所有数据" @click="refresh">
            <RefreshCw :class="metaQuery.isFetching.value ? 'animate-spin' : ''" />
          </Button>
          <RouterLink
            to="/settings"
            class="inline-flex h-9 items-center rounded-md border border-input bg-background px-3 text-xs font-medium hover:bg-accent"
          >
            访问令牌
          </RouterLink>
        </div>
      </header>

      <main class="mx-auto w-full max-w-[1680px] p-4 lg:p-6">
        <RouterView />
      </main>
    </div>
  </div>
</template>
