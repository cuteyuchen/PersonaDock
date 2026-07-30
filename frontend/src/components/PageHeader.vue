<script setup lang="ts">
defineProps<{
  eyebrow: string
  title: string
  description: string
}>()
</script>

<template>
  <header class="mb-5 flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-end sm:justify-between">
    <div class="min-w-0">
      <div class="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{{ eyebrow }}</div>
      <h2 class="text-xl font-semibold tracking-tight">{{ title }}</h2>
      <p class="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="flex shrink-0 flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
