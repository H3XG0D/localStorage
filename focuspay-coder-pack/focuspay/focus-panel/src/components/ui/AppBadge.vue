<template>
  <span class="badge" :class="[`badge--${variant ?? 'default'}`, size && `badge--${size}`]">
    <slot />
  </span>
</template>

<script setup lang="ts">
defineProps<{
  variant?: 'default' | 'green' | 'yellow' | 'red' | 'blue' | 'purple' | 'orange' | 'outline'
  size?: 'sm' | 'lg'
}>()
</script>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.2px;
  white-space: nowrap;
  border: 1px solid transparent;
}
.badge--default { background: var(--bg-elevated); color: var(--text-secondary); border-color: var(--border); }
.badge--outline  { background: transparent; color: var(--text-secondary); border-color: var(--border-strong); }
.badge--green  { background: var(--green-bg);  color: var(--green);  border-color: rgba(34,197,94,0.2); }
.badge--yellow { background: var(--yellow-bg); color: var(--yellow); border-color: rgba(234,179,8,0.2); }
.badge--red    { background: var(--red-bg);    color: var(--red);    border-color: rgba(239,68,68,0.2); }
.badge--blue   { background: var(--blue-bg);   color: var(--blue);   border-color: rgba(96,165,250,0.2); }
.badge--purple { background: var(--purple-bg); color: var(--purple); border-color: rgba(167,139,250,0.2); }
.badge--orange { background: var(--orange-bg); color: var(--orange); border-color: rgba(251,146,60,0.2); }
.badge--sm { padding: 1px 6px; font-size: 10px; }
.badge--lg { padding: 4px 11px; font-size: 12.5px; }
</style>
