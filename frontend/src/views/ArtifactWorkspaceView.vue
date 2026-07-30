<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { Archive, Download, FileArchive, KeyRound, PackageCheck, RefreshCw, ShieldCheck, Upload } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { fileToBase64, operationsApi, type ArtifactCategory, type ArtifactItem, type JsonObject } from '@/api/operations'
import PageHeader from '@/components/PageHeader.vue'
import ResultPanel from '@/components/ResultPanel.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

const route = useRoute()
const queryClient = useQueryClient()
const mode = computed(() => String(route.meta.workspace ?? 'packages'))
const personaId = ref('')
const targets = ref<string[]>(['hermes', 'openclaw', 'generic'])
const result = ref<unknown>(null)
const error = ref<string | null>(null)
const busy = ref(false)

const packagePath = ref('')
const signaturePath = ref('')
const keyName = ref('default')
const keyId = ref('')
const password = ref('')
const restoreFolder = ref('restored-persona')
const cardPath = ref('')
const cardFolder = ref('imported-character')
const cardPersonaId = ref('')
const cardLocale = ref('zh-CN')
const cardVersion = ref<2 | 3>(3)
const cardCharx = ref(false)
const adapterName = ref('hermes')
const doctorContainer = ref('')
const doctorSsh = ref('')
const skillTarget = ref('codex')
const skillScope = ref('global')
const uploaded = ref<ArtifactItem | null>(null)

const personasQuery = useQuery({ queryKey: ['personas'], queryFn: operationsApi.personas })
const exportsQuery = useQuery({ queryKey: ['artifacts', 'exports'], queryFn: () => operationsApi.artifacts('exports') })
const backupsQuery = useQuery({ queryKey: ['artifacts', 'backups'], queryFn: () => operationsApi.artifacts('backups') })
const uploadsQuery = useQuery({ queryKey: ['artifacts', 'uploads'], queryFn: () => operationsApi.artifacts('uploads') })
const keysQuery = useQuery({ queryKey: ['trust-keys'], queryFn: operationsApi.keys })
const adaptersQuery = useQuery({ queryKey: ['adapters'], queryFn: operationsApi.adapters })
const skillsQuery = useQuery({ queryKey: ['skills'], queryFn: operationsApi.skills })

watch(
  () => personasQuery.data.value?.items,
  (items) => {
    if (!personaId.value && items?.length) personaId.value = items[0].id
  },
  { immediate: true },
)

const page = computed(() => {
  if (mode.value === 'backups') return { eyebrow: 'Encrypted Private Backup', title: '备份', description: '创建、检查并恢复 AES-256-GCM 私有备份。密码不会进入 Job、日志或浏览器持久存储。' }
  if (mode.value === 'character-cards') return { eyebrow: 'Character Card Compatibility', title: 'Character Card', description: '检查、导入和导出 v2/v3 JSON、PNG 与 CHARX 兼容包。' }
  if (mode.value === 'adapters') return { eyebrow: 'Runtime Integration', title: 'Adapter 与 Skill', description: '检查 Hermes/OpenClaw Adapter，并为支持的 Agent 工具规划或安装 persona-builder Skill。' }
  return { eyebrow: 'PersonaPack Trust', title: 'PersonaPack 与信任', description: '构建目标产物、打包、检查、签名和验证 PersonaPack。' }
})

function message(value: unknown): string {
  return value instanceof Error ? value.message : String(value)
}

async function run(operation: () => Promise<unknown>, invalidate: string[] = []): Promise<void> {
  busy.value = true
  error.value = null
  try {
    result.value = await operation()
    for (const key of invalidate) await queryClient.invalidateQueries({ queryKey: [key] })
  } catch (value) {
    error.value = message(value)
  } finally {
    busy.value = false
  }
}

function toggleTarget(target: string): void {
  targets.value = targets.value.includes(target)
    ? targets.value.filter((item) => item !== target)
    : [...targets.value, target]
}

async function handleUpload(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  await run(async () => {
    const value = await operationsApi.upload(file.name, await fileToBase64(file))
    uploaded.value = value
    cardPath.value = value.path
    packagePath.value = value.path
    return value
  }, ['artifacts'])
  await queryClient.invalidateQueries({ queryKey: ['artifacts', 'uploads'] })
}

function valueId(value: JsonObject): string {
  return String(value.id ?? value.key_id ?? value.name ?? '')
}

function adapterNames(): string[] {
  const value = adaptersQuery.data.value
  if (!value) return []
  if (Array.isArray(value.items)) return value.items.map((item) => String((item as JsonObject).name ?? (item as JsonObject).id ?? item))
  if (Array.isArray(value.adapters)) return value.adapters.map((item) => String((item as JsonObject).name ?? (item as JsonObject).id ?? item))
  return Object.keys(value).filter((key) => typeof value[key] === 'object')
}
</script>

<template>
  <PageHeader :eyebrow="page.eyebrow" :title="page.title" :description="page.description">
    <template #actions>
      <Button variant="outline" :disabled="busy" @click="queryClient.invalidateQueries()"><RefreshCw class="size-4" />刷新</Button>
    </template>
  </PageHeader>

  <div class="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_460px]">
    <div class="grid content-start gap-4">
      <Card v-if="mode === 'packages'">
        <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><PackageCheck class="size-4" />构建与打包</CardTitle></CardHeader>
        <CardContent class="grid gap-4">
          <div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <label class="grid gap-1.5 text-xs"><span class="font-medium">Persona</span><select v-model="personaId" class="h-9 rounded-md border bg-background px-3"><option v-for="item in personasQuery.data.value?.items ?? []" :key="item.id" :value="item.id">{{ item.name }} · {{ item.id }}</option></select></label>
            <div class="grid gap-1.5 text-xs"><span class="font-medium">Targets</span><div class="flex h-9 items-center gap-4 rounded-md border px-3"><label v-for="target in ['hermes','openclaw','generic']" :key="target" class="flex items-center gap-1.5"><input type="checkbox" :checked="targets.includes(target)" @change="toggleTarget(target)">{{ target }}</label></div></div>
          </div>
          <div class="flex flex-wrap gap-2">
            <Button :disabled="busy || !personaId" @click="run(() => operationsApi.build(personaId, targets), ['artifacts'])">构建目标产物</Button>
            <Button variant="outline" :disabled="busy || !personaId" @click="run(() => operationsApi.pack(personaId, targets), ['artifacts'])"><FileArchive class="size-4" />创建 PersonaPack</Button>
            <Button variant="outline" :disabled="busy || !personaId" @click="run(() => operationsApi.publicExport(personaId), ['artifacts'])">公开工程导出</Button>
          </div>
        </CardContent>
      </Card>

      <Card v-if="mode === 'packages'">
        <CardHeader><CardTitle class="text-sm">包检查与签名</CardTitle></CardHeader>
        <CardContent class="grid gap-4">
          <label class="grid gap-1.5 text-xs"><span class="font-medium">PersonaPack 路径</span><Input v-model="packagePath" placeholder="选择下方导出产物，或输入受控 Artifact 路径" /></label>
          <div class="flex flex-wrap gap-2"><Button variant="outline" :disabled="busy || !packagePath" @click="run(() => operationsApi.inspectPackage(packagePath))">检查 Manifest</Button><Button variant="outline" :disabled="busy || !packagePath || !keyId" @click="run(() => operationsApi.sign(packagePath, keyId), ['artifacts'])"><KeyRound class="size-4" />签名</Button><Button variant="outline" :disabled="busy || !packagePath" @click="run(() => operationsApi.verify(packagePath, signaturePath || null))"><ShieldCheck class="size-4" />验证</Button></div>
          <div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">签名文件（可选）</span><Input v-model="signaturePath" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">签名密钥</span><select v-model="keyId" class="h-9 rounded-md border bg-background px-3"><option value="">选择密钥</option><option v-for="item in keysQuery.data.value?.items ?? []" :key="valueId(item)" :value="valueId(item)">{{ String(item.name ?? item.id) }}</option></select></label></div>
          <div class="flex gap-2"><Input v-model="keyName" class="max-w-xs" placeholder="密钥名称" /><Button variant="outline" :disabled="busy || !keyName" @click="run(() => operationsApi.createKey(keyName), ['trust-keys'])">创建 Ed25519 密钥</Button></div>
        </CardContent>
      </Card>

      <Card v-if="mode === 'backups'">
        <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><Archive class="size-4" />加密备份</CardTitle></CardHeader>
        <CardContent class="grid gap-4">
          <div class="grid gap-3 md:grid-cols-2"><label class="grid gap-1.5 text-xs"><span class="font-medium">Persona</span><select v-model="personaId" class="h-9 rounded-md border bg-background px-3"><option v-for="item in personasQuery.data.value?.items ?? []" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label class="grid gap-1.5 text-xs"><span class="font-medium">备份密码</span><Input v-model="password" type="password" autocomplete="new-password" placeholder="至少 8 个字符" /></label></div>
          <Button class="w-fit" :disabled="busy || !personaId || password.length < 8" @click="run(() => operationsApi.createBackup(personaId, password), ['artifacts'])">创建私有备份</Button>
          <div class="border-t pt-4"><div class="grid gap-3 md:grid-cols-3"><label class="grid gap-1.5 text-xs md:col-span-2"><span class="font-medium">备份路径</span><Input v-model="packagePath" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">恢复目录</span><Input v-model="restoreFolder" /></label></div><div class="mt-3 flex gap-2"><Button variant="outline" :disabled="busy || !packagePath" @click="run(() => operationsApi.inspectBackup(packagePath))">检查备份</Button><Button variant="destructive" :disabled="busy || !packagePath || !password || !restoreFolder" @click="run(() => operationsApi.restoreBackup(packagePath, password, restoreFolder), ['personas'])">解密并恢复</Button></div></div>
        </CardContent>
      </Card>

      <Card v-if="mode === 'character-cards'">
        <CardHeader><CardTitle class="text-sm">导入 Character Card</CardTitle></CardHeader>
        <CardContent class="grid gap-4">
          <label class="flex cursor-pointer items-center gap-2 rounded-md border border-dashed p-4 text-xs hover:bg-muted/40"><Upload class="size-4" /><span>选择 JSON、PNG 或 CHARX，上传到受控目录</span><input type="file" class="hidden" accept=".json,.png,.charx" @change="handleUpload"></label>
          <div v-if="uploaded" class="rounded-md border bg-muted/30 p-3 font-mono text-[11px]">{{ uploaded.path }}</div>
          <label class="grid gap-1.5 text-xs"><span class="font-medium">Card 路径</span><Input v-model="cardPath" /></label>
          <div class="grid gap-3 md:grid-cols-3"><label class="grid gap-1.5 text-xs"><span class="font-medium">目标目录</span><Input v-model="cardFolder" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Persona ID（可选）</span><Input v-model="cardPersonaId" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Locale</span><Input v-model="cardLocale" /></label></div>
          <div class="flex gap-2"><Button variant="outline" :disabled="busy || !cardPath" @click="run(() => operationsApi.inspectCard(cardPath))">检查 Card</Button><Button :disabled="busy || !cardPath || !cardFolder" @click="run(() => operationsApi.importCard(cardPath, cardFolder, cardPersonaId || null, cardLocale), ['personas'])">导入为 Persona</Button></div>
        </CardContent>
      </Card>

      <Card v-if="mode === 'character-cards'">
        <CardHeader><CardTitle class="text-sm">导出 Character Card</CardTitle></CardHeader>
        <CardContent class="grid gap-4 md:grid-cols-[minmax(0,1fr)_140px_120px_auto] md:items-end"><label class="grid gap-1.5 text-xs"><span class="font-medium">Persona</span><select v-model="personaId" class="h-9 rounded-md border bg-background px-3"><option v-for="item in personasQuery.data.value?.items ?? []" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Card 版本</span><select v-model.number="cardVersion" class="h-9 rounded-md border bg-background px-3"><option :value="3">v3</option><option :value="2">v2</option></select></label><label class="flex h-9 items-center gap-2 text-xs"><input v-model="cardCharx" type="checkbox">CHARX</label><Button :disabled="busy || !personaId" @click="run(() => operationsApi.exportCard(personaId, cardVersion, cardCharx), ['artifacts'])">导出</Button></CardContent>
      </Card>

      <Card v-if="mode === 'adapters'">
        <CardHeader><CardTitle class="text-sm">Adapter Doctor</CardTitle></CardHeader>
        <CardContent class="grid gap-4">
          <div class="flex flex-wrap gap-2"><Button v-for="name in adapterNames()" :key="name" :variant="adapterName === name ? 'default' : 'outline'" size="sm" @click="adapterName = name; run(() => operationsApi.adapter(name))">{{ name }}</Button></div>
          <div class="grid gap-3 md:grid-cols-3"><label class="grid gap-1.5 text-xs"><span class="font-medium">Adapter</span><Input v-model="adapterName" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Docker 容器（可选）</span><Input v-model="doctorContainer" /></label><label class="grid gap-1.5 text-xs"><span class="font-medium">SSH Host（可选）</span><Input v-model="doctorSsh" /></label></div>
          <Button class="w-fit" :disabled="busy || !adapterName || (!!doctorContainer && !!doctorSsh)" @click="run(() => operationsApi.doctor(adapterName, doctorContainer || null, doctorSsh || null))">运行 Doctor</Button>
        </CardContent>
      </Card>

      <Card v-if="mode === 'adapters'">
        <CardHeader><CardTitle class="text-sm">persona-builder Skill</CardTitle></CardHeader>
        <CardContent class="grid gap-4"><div class="grid gap-3 md:grid-cols-3"><label class="grid gap-1.5 text-xs"><span class="font-medium">目标工具</span><select v-model="skillTarget" class="h-9 rounded-md border bg-background px-3"><option v-for="target in skillsQuery.data.value?.targets ?? ['codex','claude','opencode','agents','generic']" :key="target">{{ target }}</option></select></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Scope</span><select v-model="skillScope" class="h-9 rounded-md border bg-background px-3"><option value="global">global</option><option value="project">project</option></select></label><label class="grid gap-1.5 text-xs"><span class="font-medium">Persona（project 必填）</span><select v-model="personaId" class="h-9 rounded-md border bg-background px-3"><option value="">选择 Persona</option><option v-for="item in personasQuery.data.value?.items ?? []" :key="item.id" :value="item.id">{{ item.name }}</option></select></label></div><div class="flex gap-2"><Button variant="outline" :disabled="busy || (skillScope === 'project' && !personaId)" @click="run(() => operationsApi.skillPlan(skillTarget, skillScope, personaId || null))">生成安装计划</Button><Button :disabled="busy || (skillScope === 'project' && !personaId)" @click="run(() => operationsApi.skillInstall(skillTarget, skillScope, personaId || null))">安装 Skill</Button></div></CardContent>
      </Card>

      <ResultPanel title="审计结果" :value="result" :error="error" @clear="result = null; error = null" />
    </div>

    <div class="grid content-start gap-4">
      <Card v-if="mode === 'packages' || mode === 'backups' || mode === 'character-cards'">
        <CardHeader><CardTitle class="text-sm">受控产物</CardTitle></CardHeader>
        <CardContent class="grid gap-3">
          <div v-for="group in (mode === 'backups' ? [backupsQuery.data.value] : mode === 'character-cards' ? [uploadsQuery.data.value, exportsQuery.data.value] : [exportsQuery.data.value])" :key="group?.category" class="grid gap-2">
            <div class="flex items-center text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground"><span>{{ group?.category }}</span><Badge variant="secondary" class="ml-auto">{{ group?.count ?? 0 }}</Badge></div>
            <button v-for="item in group?.items ?? []" :key="item.path" type="button" class="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-md border p-2 text-left hover:bg-muted/35" @click="mode === 'character-cards' ? cardPath = item.path : packagePath = item.path">
              <span class="min-w-0"><span class="block truncate text-xs font-medium">{{ item.name }}</span><span class="block truncate font-mono text-[9px] text-muted-foreground">{{ item.path }}</span></span>
              <span class="flex items-center gap-1"><Button variant="ghost" size="icon" title="下载" @click.stop="operationsApi.downloadArtifact(item.path)"><Download class="size-3.5" /></Button></span>
            </button>
            <div v-if="!group?.items?.length" class="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">暂无产物</div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle class="text-sm">安全边界</CardTitle></CardHeader>
        <CardContent class="space-y-2 text-xs text-muted-foreground"><p>上传、导出、备份和密钥均限制在 PersonaDock Artifact Root。</p><p>私钥永不出现在通用文件列表，也不能通过下载接口读取。</p><p>备份密码和部署确认令牌不会写入 Job 状态。</p></CardContent>
      </Card>
    </div>
  </div>
</template>
