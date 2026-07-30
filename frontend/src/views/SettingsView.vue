<script setup lang="ts">
import { ref } from 'vue'

import PageHeader from '@/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useSessionStore, type ThemeMode } from '@/stores/session'

const session = useSessionStore()
const token = ref(session.token)
const saved = ref(false)

function saveToken(): void {
  session.setToken(token.value)
  saved.value = true
  window.setTimeout(() => (saved.value = false), 1800)
}

function setTheme(value: Event): void {
  session.setTheme((value.target as HTMLSelectElement).value as ThemeMode)
}
</script>

<template>
  <PageHeader eyebrow="Local Settings" title="系统设置" description="这些设置只影响当前浏览器。Provider Secret、签名私钥和备份密码仍由后端安全存储。" />

  <div class="grid gap-5 xl:grid-cols-2">
    <Card>
      <CardHeader><CardTitle>访问令牌</CardTitle><CardDescription>仅在非 Loopback 或显式启用 Bearer Token 时填写。令牌保存在当前标签页的 sessionStorage。</CardDescription></CardHeader>
      <CardContent class="space-y-3">
        <label class="grid gap-1.5 text-xs font-medium" for="web-token">Bearer Token</label>
        <input id="web-token" v-model="token" type="password" autocomplete="off" class="h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring" placeholder="留空表示本机无令牌访问" />
        <div class="flex items-center gap-3"><Button @click="saveToken">保存到当前会话</Button><span v-if="saved" class="text-xs text-emerald-700 dark:text-emerald-300">已保存</span></div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle>外观</CardTitle><CardDescription>Vue 工作台支持浅色、深色和跟随系统。整体仍保持高密度桌面工具布局。</CardDescription></CardHeader>
      <CardContent>
        <label class="grid max-w-sm gap-1.5 text-xs font-medium" for="theme">主题
          <select id="theme" :value="session.theme" class="h-9 rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring" @change="setTheme">
            <option value="system">跟随系统</option>
            <option value="light">浅色</option>
            <option value="dark">深色</option>
          </select>
        </label>
      </CardContent>
    </Card>

    <Card class="xl:col-span-2">
      <CardHeader><CardTitle>前端迁移状态</CardTitle><CardDescription>Vue 3 + TypeScript + Vite + shadcn-vue 已作为并行工作台接入，旧界面暂时保留用于尚未迁移的写操作。</CardDescription></CardHeader>
      <CardContent>
        <div class="grid gap-px overflow-hidden rounded-md border bg-border sm:grid-cols-4">
          <div class="bg-card p-3"><div class="text-[10px] text-muted-foreground">框架</div><div class="mt-1 text-sm font-medium">Vue 3</div></div>
          <div class="bg-card p-3"><div class="text-[10px] text-muted-foreground">组件</div><div class="mt-1 text-sm font-medium">shadcn-vue</div></div>
          <div class="bg-card p-3"><div class="text-[10px] text-muted-foreground">样式</div><div class="mt-1 text-sm font-medium">Tailwind CSS 4</div></div>
          <div class="bg-card p-3"><div class="text-[10px] text-muted-foreground">发布</div><div class="mt-1 text-sm font-medium">嵌入 Python / PyInstaller</div></div>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
