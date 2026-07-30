<script setup lang="ts">
import { computed } from 'vue'

import { Badge, type BadgeVariants } from '@/components/ui/badge'

const props = defineProps<{
  status: string | boolean | null | undefined
  label?: string
}>()

const normalized = computed(() => String(props.status ?? 'unknown').toLowerCase())
const variant = computed<BadgeVariants['variant']>(() => {
  if (['success', 'ready', 'managed', 'approved', 'applied', 'verified', 'ok'].includes(normalized.value)) return 'success'
  if (['queued', 'running', 'waiting-review', 'pending', 'unmanaged', 'planned'].includes(normalized.value)) return 'warning'
  if (['failed', 'rejected', 'cancelled', 'error', 'conflict'].includes(normalized.value)) return 'destructive'
  return 'outline'
})
</script>

<template>
  <Badge :variant="variant">{{ label ?? normalized }}</Badge>
</template>
