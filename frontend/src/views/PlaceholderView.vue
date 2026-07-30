<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

const route = useRoute()
const title = computed(() => String(route.meta.title ?? '功能页面'))
const legacyHash = computed(() => String(route.meta.legacyHash ?? '#/overview'))
</script>

<template>
  <PageHeader eyebrow="Vue Migration" :title="title" description="后端能力已经可用，此页面正在从原生 JavaScript 工作台迁移到 Vue 与 shadcn-vue。迁移期间不会复制或改写后端契约。" />
  <Card class="max-w-3xl">
    <CardHeader><CardTitle>使用兼容界面继续操作</CardTitle><CardDescription>该入口会打开已经通过完整 bundle 验证的旧工作台。Vue 页面完成同等测试后再替换。</CardDescription></CardHeader>
    <CardContent>
      <a :href="`/${legacyHash}`" class="inline-flex h-9 items-center rounded-md bg-primary px-3.5 text-sm font-medium text-primary-foreground hover:bg-primary/90">打开 {{ title }} 兼容页面</a>
    </CardContent>
  </Card>
</template>
