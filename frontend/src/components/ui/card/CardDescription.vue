<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <p data-slot="card-description" :class="cn('text-xs leading-5 text-muted-foreground', $props.class)">
    <slot />
  </p>
</template>
