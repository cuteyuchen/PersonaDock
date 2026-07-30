<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <header data-slot="card-header" :class="cn('flex flex-col gap-1 border-b px-4 py-3', $props.class)">
    <slot />
  </header>
</template>
