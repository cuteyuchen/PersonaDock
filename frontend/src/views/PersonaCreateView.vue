<script setup lang="ts">
import { toTypedSchema } from '@vee-validate/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { FolderPlus, ShieldCheck } from 'lucide-vue-next'
import { useForm } from 'vee-validate'
import { computed } from 'vue'
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
const schema = toTypedSchema(z.object({
  id: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, '仅允许小写字母、数字和连字符'),
  name: z.string().min(1, '请输入名称').max(160),
  locale: z.string().min(2).max(32),
  folder: z.string().regex(/^(?![\\/])(?!.*(?:^|[\\/])\.\.(?:[\\/]|$)).+$/, '目录必须是安全的相对路径'),
}))
const { defineField, errors, handleSubmit, isSubmitting, setFieldValue } = useForm({
  validationSchema: schema,
  initialValues: { id: '', name: '', locale: 'zh-CN', folder: '' },
})
const [id] = defineField('id')
const [name] = defineField('name')
const [locale] = defineField('locale')
const [folder] = defineField('folder')

const destination = computed(() => {
  const root = rootsQuery.data.value?.default_root ?? '默认 Persona 根目录'
  return `${root}/${folder.value || id.value || '<目录>'}`
})

function syncFolder(): void {
  if (!folder.value.trim()) setFieldValue('folder', id.value)
}

const mutation = useMutation({
  mutationFn: personasApi.create,
  onSuccess: async (result) => {
    await queryClient.invalidateQueries({ queryKey: ['personas'] })
    await router.push(`/personas/${encodeURIComponent(result.persona.id)}`)
  },
})

const submit = handleSubmit(async (values) => {
  await mutation.mutateAsync({ ...values, folder: values.folder || values.id })
})
</script>

<template>
  <PageHeader eyebrow="Persona Lifecycle" title="新建 Persona" description="在受控工作区创建 Canonical Persona v3 工程，并立即注册到本地 Registry。" />

  <div class="grid gap-4 xl:grid-cols-[minmax(0,720px)_360px]">
    <Card>
      <CardHeader><CardTitle class="text-sm">基本信息</CardTitle></CardHeader>
      <CardContent>
        <form class="grid gap-5" @submit="submit">
          <div class="grid gap-4 md:grid-cols-2">
            <FormField label="Persona ID" for-id="persona-id" required :error="errors.id" description="稳定标识，创建后不可修改。">
              <Input id="persona-id" v-model="id" autocomplete="off" placeholder="xiaoyou" @blur="syncFolder" />
            </FormField>
            <FormField label="显示名称" for-id="persona-name" required :error="errors.name">
              <Input id="persona-name" v-model="name" placeholder="小柚" />
            </FormField>
          </div>
          <div class="grid gap-4 md:grid-cols-2">
            <FormField label="Locale" for-id="persona-locale" :error="errors.locale">
              <Input id="persona-locale" v-model="locale" placeholder="zh-CN" />
            </FormField>
            <FormField label="工程目录" for-id="persona-folder" required :error="errors.folder" description="相对于默认 Persona 根目录，不允许绝对路径或 ..。">
              <Input id="persona-folder" v-model="folder" placeholder="xiaoyou" />
            </FormField>
          </div>

          <div v-if="mutation.isError.value" class="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            {{ mutation.error.value instanceof Error ? mutation.error.value.message : '创建失败' }}
          </div>

          <div class="flex items-center justify-end gap-2 border-t pt-4">
            <Button type="button" variant="outline" @click="router.push('/personas')">取消</Button>
            <Button type="submit" :disabled="isSubmitting || mutation.isPending.value">
              <FolderPlus class="size-4" />
              {{ mutation.isPending.value ? '正在创建…' : '创建并注册' }}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>

    <div class="grid content-start gap-4">
      <Card>
        <CardHeader><CardTitle class="text-sm">写入位置</CardTitle></CardHeader>
        <CardContent class="space-y-3 text-xs">
          <div class="rounded-md border bg-muted/35 p-3 font-mono break-all">{{ destination }}</div>
          <div class="text-muted-foreground">允许根目录由 <code>{{ rootsQuery.data.value?.environment ?? 'PERSONADOCK_PERSONA_ROOTS' }}</code> 控制。</div>
          <ul class="space-y-1 font-mono text-[10px] text-muted-foreground">
            <li v-for="root in rootsQuery.data.value?.roots ?? []" :key="root">{{ root }}</li>
          </ul>
        </CardContent>
      </Card>
      <Card>
        <CardContent class="flex gap-3 p-4 text-xs text-muted-foreground">
          <ShieldCheck class="mt-0.5 size-4 shrink-0 text-emerald-600" />
          <p>创建仅写入配置的 Persona 根目录，不允许浏览器指定任意绝对路径。工程默认包含 Canonical v3、人格 Skill、Memory Policy 和场景测试。</p>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
