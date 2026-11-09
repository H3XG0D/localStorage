<template>
  <div class="input-wrap" :class="{ 'input-wrap--error': error }">
    <label v-if="label" class="input-label" :for="id">{{ label }}</label>
    <div class="input-inner">
      <span v-if="$slots.prefix" class="input-affix input-affix--left">
        <slot name="prefix" />
      </span>
      <input
        :id="id"
        class="input-field"
        :class="{ 'has-prefix': $slots.prefix, 'has-suffix': $slots.suffix }"
        v-bind="$attrs"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :type="type ?? 'text'"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="$slots.suffix" class="input-affix input-affix--right">
        <slot name="suffix" />
      </span>
    </div>
    <p v-if="error" class="input-hint input-hint--error">{{ error }}</p>
    <p v-else-if="hint" class="input-hint">{{ hint }}</p>
  </div>
</template>

<script setup lang="ts">
import { useId } from 'vue'

defineOptions({ inheritAttrs: false })

defineProps<{
  modelValue?: string | number
  label?: string
  placeholder?: string
  error?: string
  hint?: string
  disabled?: boolean
  type?: string
}>()

const emit = defineEmits<{ (e: 'update:modelValue', val: string): void }>()
const id = useId()
</script>

<style scoped>
.input-wrap { display: flex; flex-direction: column; gap: 5px; }

.input-label { font-size: 12px; font-weight: 500; color: var(--text-secondary); }

.input-inner { position: relative; display: flex; align-items: center; }

.input-field {
  width: 100%;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  color: var(--text-primary);
  padding: 8px 12px;
  font-size: 13px;
  transition: border-color var(--transition), box-shadow var(--transition);
  outline: none;
}
.input-field::placeholder { color: var(--text-muted); }
.input-field:focus {
  border-color: var(--text-muted);
  box-shadow: 0 0 0 3px rgba(255,255,255,0.05);
}
.input-field.has-prefix { padding-left: 34px; }
.input-field.has-suffix { padding-right: 34px; }
.input-field:disabled { opacity: 0.38; cursor: not-allowed; }

.input-wrap--error .input-field { border-color: rgba(239,68,68,0.5); }
.input-wrap--error .input-field:focus { box-shadow: 0 0 0 3px rgba(239,68,68,0.1); }

.input-affix {
  position: absolute;
  display: flex;
  align-items: center;
  color: var(--text-muted);
  pointer-events: none;
}
.input-affix--left  { left: 10px; }
.input-affix--right { right: 10px; }

.input-hint { font-size: 11.5px; color: var(--text-muted); }
.input-hint--error { color: var(--red); }
</style>
