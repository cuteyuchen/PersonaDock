<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { computed } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class']; modelValue?: string; placeholder?: string; disabled?: boolean; rows?: string | number }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const normalizedRows = computed(() => {
  const value = Number(props.rows ?? 4)
  return Number.isFinite(value) && value > 0 ? value : 4
})
</script>

<template>
  <textarea
    :value="modelValue ?? ''"
    :placeholder="placeholder"
    :disabled="disabled"
    :rows="normalizedRows"
    :class="cn('flex min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50', $props.class)"
    @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
  />
</template>
