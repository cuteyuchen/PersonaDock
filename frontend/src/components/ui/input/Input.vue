<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
  modelValue?: string | number
  type?: string
  placeholder?: string
  disabled?: boolean
  modelModifiers?: { number?: boolean }
}>()
const emit = defineEmits<{ 'update:modelValue': [value: any] }>()

function update(event: Event): void {
  const value = (event.target as HTMLInputElement).value
  emit('update:modelValue', props.type === 'number' || props.modelModifiers?.number ? Number(value) : value)
}
</script>

<template>
  <input
    :type="type ?? 'text'"
    :value="modelValue ?? ''"
    :placeholder="placeholder"
    :disabled="disabled"
    :class="cn('flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50', $props.class)"
    @input="update"
  >
</template>
