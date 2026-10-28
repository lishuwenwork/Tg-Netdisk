<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "ghost" | "danger";
    busy?: boolean;
  }>(),
  { variant: "secondary" },
);
</script>
<template>
  <button
    class="btn"
    :class="[`btn-${variant}`, { busy }]"
    :disabled="busy"
    type="button"
  >
    <span v-if="busy" class="spinner" /><slot />
  </button>
</template>
