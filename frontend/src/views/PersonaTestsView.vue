<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { CheckCircle2, ClipboardCheck, FileWarning, Play, RefreshCw, TerminalSquare, XCircle } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { personasApi } from '@/api/personas'
import type { PersonaTestResult, ValidationResult } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import PersonaTabs from '@/components/persona/PersonaTabs.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const route = useRoute()
const queryClient = useQueryClient()
const personaId = computed(() => String(route.params.personaId))
const validation = ref<ValidationResult | null>(null)
const tests = ref<PersonaTestResult | null>(null)
const migrationPlan = ref<Record<string, unknown> | null>(null)

const personaQuery = useQuery({ queryKey: computed(() => ['persona', personaId.value]), queryFn: () => personasApi.get(personaId.value) })
const compileQuery = useQuery({ queryKey: computed(() => ['persona-compile', personaId.value]), queryFn: () => personasApi.compilePreview(personaId.value), retry: false })
const validateMutation = useMutation({ mutationFn: () => personasApi.validate(personaId.value), onSuccess: (value) => { validation.value = value } })
const testMutation = useMutation({ mutationFn: () => personasApi.test(personaId.value), onSuccess: (value) => { tests.value = value.result } })
const migrationPreviewMutation = useMutation({ mutationFn: () => personasApi.migratePreview(personaId.value), onSuccess: (value) => { migrationPlan.value = value } })
const migrationMutation = useMutation({
  mutationFn: () => personasApi.migrate(personaId.value),
  onSuccess: async () => {
    migrationPlan.value = null
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['persona', personaId.value] }),
      queryClient.invalidateQueries({ queryKey: ['personas'] }),
      queryClient.invalidateQueries({ queryKey: ['persona-canonical', personaId.value] }),
      queryClient.invalidateQueries({ queryKey: ['persona-revisions', personaId.value] }),
      queryClient.invalidateQueries({ queryKey: ['persona-compile', personaId.value] }),
    ])
  },
})
</script>

<template>
  <PageHeader eyebrow="Quality Gate" title="验证与场景测试" description="检查工程结构、Canonical 约束、行为链接和编译预算；Schema 迁移必须先预览。">
    <template #actions><Button variant="outline" :disabled="validateMutation.isPending.value" @click="validateMutation.mutate()"><RefreshCw class="size-4" />验证</Button><Button :disabled="testMutation.isPending.value" @click="testMutation.mutate()"><Play class="size-4" />运行测试</Button></template>
  </PageHeader>
  <PersonaTabs :persona-id="personaId" />

  <div v-if="personaQuery.data.value?.schema_version !== 3" class="mb-4 rounded-md border border-amber-300 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/25">
    <div class="flex items-start gap-3"><FileWarning class="mt-0.5 size-5 shrink-0 text-amber-700" /><div class="min-w-0 flex-1"><div class="text-sm font-semibold">Canonical Schema v{{ personaQuery.data.value?.schema_version }} 需要迁移</div><p class="mt-1 text-xs text-amber-900/75 dark:text-amber-200/75">迁移会在原工程内生成 v3 Canonical，并在写入前创建备份。先生成计划确认 from/to Schema。</p><div class="mt-3 flex gap-2"><Button variant="outline" size="sm" :disabled="migrationPreviewMutation.isPending.value" @click="migrationPreviewMutation.mutate()">预览迁移</Button><Button v-if="migrationPlan" size="sm" :disabled="migrationMutation.isPending.value" @click="migrationMutation.mutate()">确认迁移到 v3</Button></div><pre v-if="migrationPlan" class="mt-3 overflow-auto rounded-md border bg-background p-3 text-[10px]">{{ JSON.stringify(migrationPlan, null, 2) }}</pre></div></div>
  </div>

  <Tabs default-value="results">
    <TabsList><TabsTrigger value="results"><ClipboardCheck class="mr-1.5 size-3.5" />结果</TabsTrigger><TabsTrigger value="compile"><TerminalSquare class="mr-1.5 size-3.5" />编译产物</TabsTrigger></TabsList>
    <TabsContent value="results">
      <div class="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle class="flex items-center justify-between text-sm"><span>项目校验</span><Badge v-if="validation" :variant="validation.ok ? 'secondary' : 'destructive'">{{ validation.ok ? '通过' : '失败' }}</Badge></CardTitle></CardHeader>
          <CardContent>
            <div v-if="!validation" class="py-8 text-center text-xs text-muted-foreground">点击“验证”检查工程。</div>
            <div v-else-if="validation.ok" class="flex items-center gap-2 text-xs text-emerald-700 dark:text-emerald-300"><CheckCircle2 class="size-4" />工程结构与 Canonical 校验通过。</div>
            <ul v-else class="space-y-2 text-xs text-red-700 dark:text-red-300"><li v-for="error in validation.errors" :key="error" class="flex gap-2"><XCircle class="mt-0.5 size-3.5 shrink-0" />{{ error }}</li></ul>
            <div v-if="validateMutation.isError.value" class="mt-3 text-xs text-red-700">{{ validateMutation.error.value instanceof Error ? validateMutation.error.value.message : '验证失败' }}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle class="flex items-center justify-between text-sm"><span>场景测试</span><Badge v-if="tests" :variant="tests.ok ? 'secondary' : 'destructive'">{{ tests.ok ? '通过' : '失败' }}</Badge></CardTitle></CardHeader>
          <CardContent>
            <div v-if="!tests" class="py-8 text-center text-xs text-muted-foreground">点击“运行测试”执行 Persona 场景测试，任务记录会进入 Job Center。</div>
            <div v-else class="space-y-3"><div class="grid grid-cols-3 gap-2 text-center"><div class="rounded-md border p-3"><div class="text-lg font-semibold">{{ tests.total ?? tests.results?.length ?? 0 }}</div><div class="text-[10px] text-muted-foreground">总计</div></div><div class="rounded-md border p-3"><div class="text-lg font-semibold text-emerald-600">{{ tests.passed ?? '—' }}</div><div class="text-[10px] text-muted-foreground">通过</div></div><div class="rounded-md border p-3"><div class="text-lg font-semibold text-red-600">{{ tests.failed ?? '—' }}</div><div class="text-[10px] text-muted-foreground">失败</div></div></div><pre class="max-h-[420px] overflow-auto rounded-md border bg-muted/35 p-3 text-[10px]">{{ JSON.stringify(tests, null, 2) }}</pre></div>
            <div v-if="testMutation.isError.value" class="mt-3 text-xs text-red-700">{{ testMutation.error.value instanceof Error ? testMutation.error.value.message : '测试失败' }}</div>
          </CardContent>
        </Card>
      </div>
    </TabsContent>
    <TabsContent value="compile">
      <div v-if="compileQuery.isPending.value" class="py-12 text-center text-xs text-muted-foreground">正在编译…</div>
      <div v-else-if="compileQuery.isError.value" class="rounded-md border border-amber-300 bg-amber-50 p-4 text-xs text-amber-900">{{ compileQuery.error.value instanceof Error ? compileQuery.error.value.message : '当前 Schema 无法编译' }}</div>
      <div v-else-if="compileQuery.data.value" class="grid gap-4 xl:grid-cols-2"><Card><CardHeader><CardTitle class="flex items-center justify-between text-sm"><span>SOUL</span><Badge :variant="compileQuery.data.value.soul_chars > (compileQuery.data.value.hard_limit_chars ?? Infinity) ? 'destructive' : 'outline'">{{ compileQuery.data.value.soul_chars }} / {{ compileQuery.data.value.hard_limit_chars ?? '∞' }}</Badge></CardTitle></CardHeader><CardContent><pre class="max-h-[620px] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/35 p-4 text-xs leading-5">{{ compileQuery.data.value.soul }}</pre></CardContent></Card><Card><CardHeader><CardTitle class="text-sm">Persona Skill</CardTitle></CardHeader><CardContent><pre class="max-h-[620px] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/35 p-4 text-xs leading-5">{{ compileQuery.data.value.skill }}</pre></CardContent></Card></div>
    </TabsContent>
  </Tabs>
</template>
