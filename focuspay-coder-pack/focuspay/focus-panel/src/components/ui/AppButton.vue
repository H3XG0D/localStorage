<template>
  <button
    class="btn"
    :class="[
      `btn--${variant ?? 'secondary'}`,
      `btn--${size ?? 'md'}`,
      { 'btn--loading': loading, 'btn--icon-only': iconOnly }
    ]"
    :disabled="disabled || loading"
    v-bind="$attrs"
  >
    <span v-if="loading" class="btn-spinner" aria-hidden="true" />
    <slot />
  </button>
</template>

<script setup lang="ts">
defineProps<{
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  disabled?: boolean
  iconOnly?: boolean
}>()
</script>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: var(--radius);
  font-weight: 500;
  font-family: var(--font);
  transition: background var(--transition), border-color var(--transition), color var(--transition), opacity var(--transition);
  white-space: nowrap;
  cursor: pointer;
  border: 1px solid transparent;
  letter-spacing: 0.1px;
  outline: none;
}
.btn:focus-visible { box-shadow: 0 0 0 2px var(--bg-base), 0 0 0 4px var(--border-strong); }
.btn:disabled { opacity: 0.38; cursor: not-allowed; pointer-events: none; }

.btn--sm { padding: 5px 11px; font-size: 12px; }
.btn--md { padding: 7px 15px; font-size: 13px; }
.btn--lg { padding: 10px 20px; font-size: 14px; }

.btn--icon-only.btn--sm { padding: 5px; width: 28px; height: 28px; border-radius: var(--radius-sm); }
.btn--icon-only.btn--md { padding: 7px; width: 34px; height: 34px; }
.btn--icon-only.btn--lg { padding: 9px; width: 40px; height: 40px; }

.btn--primary  { background: var(--text-primary); color: var(--text-inverse); border-color: var(--text-primary); }
.btn--primary:hover:not(:disabled)  { background: var(--accent-hover); border-color: var(--accent-hover); }

.btn--secondary { background: var(--bg-elevated); color: var(--text-primary); border-color: var(--border-strong); }
.btn--secondary:hover:not(:disabled) { background: var(--bg-overlay); }

.btn--ghost { background: transparent; color: var(--text-secondary); }
.btn--ghost:hover:not(:disabled) { background: var(--bg-elevated); color: var(--text-primary); }

.btn--outline { background: transparent; color: var(--text-primary); border-color: var(--border-strong); }
.btn--outline:hover:not(:disabled) { background: var(--bg-elevated); }

.btn--danger { background: var(--red-bg); color: var(--red); border-color: rgba(239,68,68,0.25); }
.btn--danger:hover:not(:disabled) { background: rgba(239,68,68,0.18); }

.btn-spinner {
  width: 12px; height: 12px;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: btn-spin 0.55s linear infinite;
  flex-shrink: 0;
}
@keyframes btn-spin { to { transform: rotate(360deg); } }
</style>
