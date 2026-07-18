<script setup lang="ts">
import { zhCN } from "../locales/zh-CN";

withDefaults(defineProps<{ modelValue: number; disabled?: boolean; label?: string }>(), {
  disabled: false,
  label: zhCN.rating,
});

const emit = defineEmits<{ "update:modelValue": [value: number] }>();
</script>

<template>
  <fieldset class="rating-picker" :disabled="disabled">
    <legend class="sr-only">{{ label }}</legend>
    <button
      v-for="value in 5"
      :key="value"
      type="button"
      class="rating-star"
      :class="{ active: value <= modelValue }"
      :aria-label="zhCN.stars(value)"
      :aria-pressed="value === modelValue"
      @click="emit('update:modelValue', value === modelValue ? 0 : value)"
    >★</button>
  </fieldset>
</template>
