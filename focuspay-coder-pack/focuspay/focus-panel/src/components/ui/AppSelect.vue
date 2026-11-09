<template>
  <div class="select-wrap">
    <label v-if="label" class="select-label">{{ label }}</label>
    <div class="select-inner">
      <select
        class="select-field"
        :value="modelValue"
        :disabled="disabled"
        @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option v-if="placeholder" value="" disabled :selected="!modelValue">{{ placeholder }}</option>
        <option v-for="opt in options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <svg class="select-chevron" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M2 4.5l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  modelValue?: string
  label?: string
  placeholder?: string
  options: { value: string; label: string }[]
  disabled?: boolean
}>()
const emit = defineEmits<{ (e: 'update:modelValue', val: string): void }>()
</script>

<style scoped>
.select-wrap { display: flex; flex-direction: column; gap: 5px; }
.select-label { font-size: 12px; font-weight: 500; color: var(--text-secondary); }
.select-inner { position: relative; }

.select-field {
  width: 100%;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  color: var(--text-primary);
  padding: 8px 32px 8px 12px;
  font-size: 13px;
  appearance: none;
  cursor: pointer;
  outline: none;
  transition: border-color var(--transition);
}
.select-field:focus { border-color: var(--text-muted); }
.select-field option { background: var(--bg-elevated); }
.select-field:disabled { opacity: 0.38; cursor: not-allowed; }

.select-chevron {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-muted);
  pointer-events: none;
}
</style>
