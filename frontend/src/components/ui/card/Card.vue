<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <section data-slot="card" :class="cn('rounded-md border bg-card text-card-foreground shadow-sm', $props.class)">
    <slot />
  </section>
</template>
