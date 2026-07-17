<script setup lang="ts">
defineProps<{
  title: string;
  message?: string;
  kind?: "loading" | "empty" | "error" | "unavailable";
  action?: string;
}>();

defineEmits<{ action: [] }>();
</script>

<template>
  <section class="state-panel" :class="`state-${kind ?? 'empty'}`" :aria-busy="kind === 'loading'" :role="kind === 'error' ? 'alert' : 'status'">
    <span class="state-mark" aria-hidden="true">{{ kind === "loading" ? "···" : kind === "error" ? "!" : kind === "unavailable" ? "×" : "○" }}</span>
    <h2>{{ title }}</h2>
    <p v-if="message">{{ message }}</p>
    <button v-if="action" class="text-button" type="button" @click="$emit('action')">{{ action }}</button>
  </section>
</template>
