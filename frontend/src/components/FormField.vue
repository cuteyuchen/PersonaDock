<script setup lang="ts">
defineProps<{ label: string; description?: string; error?: string; required?: boolean; forId?: string }>()
</script>

<template>
  <div class="grid gap-1.5">
    <label :for="forId" class="text-xs font-medium text-foreground">
      {{ label }}<span v-if="required" class="ml-0.5 text-red-600">*</span>
    </label>
    <slot />
    <p v-if="error" class="text-[11px] text-red-600 dark:text-red-400">{{ error }}</p>
    <p v-else-if="description" class="text-[11px] leading-4 text-muted-foreground">{{ description }}</p>
  </div>
</template>
