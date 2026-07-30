<script setup lang="ts">
import { Braces, ClipboardCheck, GitBranch, LayoutPanelTop } from 'lucide-vue-next'
import { RouterLink, useRoute } from 'vue-router'

const props = defineProps<{ personaId: string }>()
const route = useRoute()
const tabs = [
  ['overview', '概览', LayoutPanelTop, `/personas/${encodeURIComponent(props.personaId)}`],
  ['editor', 'Canonical 编辑', Braces, `/personas/${encodeURIComponent(props.personaId)}/editor`],
  ['revisions', 'Revision 与 Diff', GitBranch, `/personas/${encodeURIComponent(props.personaId)}/revisions`],
  ['tests', '验证与测试', ClipboardCheck, `/personas/${encodeURIComponent(props.personaId)}/tests`],
] as const
</script>

<template>
  <nav class="mb-4 flex gap-1 overflow-x-auto border-b" aria-label="Persona 详情导航">
    <RouterLink
      v-for="tab in tabs"
      :key="tab[0]"
      :to="tab[3]"
      class="flex h-10 shrink-0 items-center gap-2 border-b-2 border-transparent px-3 text-xs font-medium text-muted-foreground hover:text-foreground"
      :class="route.meta.personaTab === tab[0] ? 'border-foreground text-foreground' : ''"
    >
      <component :is="tab[2]" class="size-3.5" />
      {{ tab[1] }}
    </RouterLink>
  </nav>
</template>
