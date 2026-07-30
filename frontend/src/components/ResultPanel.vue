<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ title?: string; value: unknown; error?: string | null }>()
const formatted = computed(() => {
  if (props.value === null || props.value === undefined) return ''
  return typeof props.value === 'string' ? props.value : JSON.stringify(props.value, null, 2)
})
</script>

<template>
  <section v-if="error || formatted" class="rounded-md border bg-card">
    <div class="flex items-center border-b px-3 py-2 text-xs font-medium">
      {{ title ?? '操作结果' }}
      <button class="ml-auto text-[11px] text-muted-foreground hover:text-foreground" type="button" @click="$emit('clear')">清除</button>
    </div>
    <div v-if="error" class="border-b bg-red-50 px-3 py-2 text-xs text-red-800 dark:bg-red-950/30 dark:text-red-300">{{ error }}</div>
    <pre v-if="formatted" class="max-h-[460px] overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-5">{{ formatted }}</pre>
  </section>
</template>
