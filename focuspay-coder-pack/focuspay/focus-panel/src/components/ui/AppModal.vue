<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="modelValue" class="modal-backdrop" @click.self="close" role="dialog" aria-modal="true" :aria-label="title">
        <div class="modal" :style="maxWidth ? { maxWidth } : {}">
          <div class="modal-header">
            <div class="modal-heading">
              <h3 class="modal-title">{{ title }}</h3>
              <p v-if="subtitle" class="modal-subtitle">{{ subtitle }}</p>
            </div>
            <button class="modal-close" @click="close" aria-label="Закрыть">
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                <path d="M1.5 1.5l12 12M13.5 1.5l-12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>
          <div class="modal-body"><slot /></div>
          <div v-if="$slots.footer" class="modal-footer"><slot name="footer" /></div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
defineProps<{ modelValue: boolean; title: string; subtitle?: string; maxWidth?: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()
function close() { emit('update:modelValue', false) }
</script>

<style scoped>
.modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.72);
  backdrop-filter: blur(6px);
  display: flex; align-items: center; justify-content: center;
  padding: 20px; z-index: 900;
}

.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xl);
  width: 100%; max-width: 520px;
  max-height: 90dvh; overflow: hidden;
  display: flex; flex-direction: column;
  box-shadow: var(--shadow-lg);
}

.modal-header {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
  padding: 22px 22px 0;
}

.modal-title   { font-size: 16px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.3px; }
.modal-subtitle { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

.modal-close {
  color: var(--text-muted); padding: 5px;
  border-radius: var(--radius-sm);
  transition: color var(--transition), background var(--transition);
  flex-shrink: 0; cursor: pointer; display: flex;
}
.modal-close:hover { color: var(--text-primary); background: var(--bg-elevated); }

.modal-body {
  padding: 18px 22px;
  overflow-y: auto; flex: 1;
  display: flex; flex-direction: column; gap: 14px;
}

.modal-footer {
  padding: 14px 22px 18px;
  border-top: 1px solid var(--border);
  display: flex; gap: 8px; justify-content: flex-end;
}

.modal-enter-active, .modal-leave-active { transition: opacity 180ms ease; }
.modal-enter-active .modal, .modal-leave-active .modal { transition: transform 180ms ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
.modal-enter-from .modal { transform: scale(0.96) translateY(10px); }
.modal-leave-to .modal { transform: scale(0.96) translateY(10px); }
</style>
