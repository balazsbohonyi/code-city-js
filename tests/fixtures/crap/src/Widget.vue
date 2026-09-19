<template>
  <div>{{ label }}</div>
</template>

<script setup lang="ts">
export function score(x: number) {
  if (x > 0) {
    return x;
  }
  return 0;
}
</script>
