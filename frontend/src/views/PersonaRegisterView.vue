<script setup lang="ts">
import { toTypedSchema } from '@vee-validate/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { FolderSearch, ShieldCheck } from 'lucide-vue-next'
import { useForm } from 'vee-validate'
import { useRouter } from 'vue-router'
import { z } from 'zod'

import { personasApi } from '@/api/personas'
import FormField from '@/components/FormField.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

const router = useRouter()
const queryClient = useQueryClient()
const rootsQuery = useQuery({ queryKey: ['persona-roots'], queryFn: personasApi.roots })
const { defineField, errors, handleSubmit, isSubmitting } = useForm({
  validationSchema: toTypedSchema(z.object({ path: z.string().min(1, '请输入 Persona 工程路径').max(1024) })),
  initialValues: { path: '' },
})
const [path] = defineField('path')
const mutation = useMutation({
  mutationFn: personasApi.register,
  onSuccess: async (result) => {
    await queryClient.invalidateQueries({ queryKey: ['personas'] })
    await router.push(`/personas/${encodeURIComponent(result.persona.id)}`)
  },
})
const submit = handleSubmit(async (values) => mutation.mutateAsync(values.path))
</script>

<template>
  <PageHeader eyebrow="Persona Lifecycle" title="注册现有工程" description="校验已有 PersonaDock 工程并加入 Registry，不复制或重写工程内容。" />

  <div class="grid gap-4 xl:grid-cols-[minmax(0,720px)_360px]">
    <Card>
      <CardHeader><CardTitle class="text-sm">工程路径</CardTitle></CardHeader>
      <CardContent>
        <form class="grid gap-5" @submit="submit">
          <FormField label="Persona 工程" for-id="persona-path" required :error="errors.path" description="可输入允许根目录内的绝对路径，或相对于默认根目录的路径。目录中必须包含 companion.yaml。">
            <Input id="persona-path" v-model="path" class="font-mono text-xs" placeholder="existing-persona 或 /allowed/root/existing-persona" />
          </FormField>
          <div v-if="mutation.isError.value" class="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            {{ mutation.error.value instanceof Error ? mutation.error.value.message : '注册失败' }}
          </div>
          <div class="flex items-center justify-end gap-2 border-t pt-4">
            <Button type="button" variant="outline" @click="router.push('/personas')">取消</Button>
            <Button type="submit" :disabled="isSubmitting || mutation.isPending.value"><FolderSearch class="size-4" />{{ mutation.isPending.value ? '正在校验…' : '校验并注册' }}</Button>
          </div>
        </form>
      </CardContent>
    </Card>

    <Card class="h-fit">
      <CardHeader><CardTitle class="text-sm">允许访问的根目录</CardTitle></CardHeader>
      <CardContent class="space-y-3 text-xs text-muted-foreground">
        <div class="flex gap-2"><ShieldCheck class="mt-0.5 size-4 shrink-0 text-emerald-600" /><p>后端会解析真实路径并检查其是否属于允许根目录，符号链接不能绕过限制。</p></div>
        <ul class="space-y-1 rounded-md border bg-muted/35 p-3 font-mono text-[10px]">
          <li v-for="root in rootsQuery.data.value?.roots ?? []" :key="root" class="break-all">{{ root }}</li>
        </ul>
      </CardContent>
    </Card>
  </div>
</template>
