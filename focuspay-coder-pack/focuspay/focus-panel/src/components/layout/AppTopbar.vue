<template>
  <header class="topbar">
    <!-- Left: page title from route meta -->
    <div class="topbar-left">
      <h1 class="topbar-title">{{ pageTitle }}</h1>
    </div>

    <!-- Right: actions -->
    <div class="topbar-right">
      <!-- Search shortcut -->
      <button class="topbar-search-btn" @click="$router.push('/search')" aria-label="Поиск">
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
          <circle cx="6" cy="6" r="4.5" stroke="currentColor" stroke-width="1.5"/>
          <path d="M10 10l3.5 3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        <span>Поиск...</span>
        <kbd>⌘K</kbd>
      </button>

      <!-- Notifications -->
      <button class="topbar-icon-btn" aria-label="Уведомления">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M8 1.5a5 5 0 00-5 5v2.5L1.5 11h13L13 9V6.5a5 5 0 00-5-5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
          <path d="M6.5 13.5a1.5 1.5 0 003 0" stroke="currentColor" stroke-width="1.5"/>
        </svg>
        <span class="notif-dot" aria-hidden="true" />
      </button>

      <!-- Avatar -->
      <button class="topbar-avatar" aria-label="Профиль">
        <span>АД</span>
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const pageTitle = computed(() => (route.meta?.title as string) ?? 'FocusPanel')
</script>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--topbar-h);
  padding: 0 24px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
  flex-shrink: 0;
  gap: 16px;
}

.topbar-left { display: flex; align-items: center; gap: 12px; }
.topbar-title { font-size: 15px; font-weight: 600; color: var(--text-primary); letter-spacing: -0.2px; }

.topbar-right { display: flex; align-items: center; gap: 6px; }

.topbar-search-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 12.5px;
  cursor: pointer;
  transition: border-color var(--transition), color var(--transition);
  white-space: nowrap;
}
.topbar-search-btn:hover { border-color: var(--text-muted); color: var(--text-secondary); }

kbd {
  background: var(--bg-overlay);
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 10.5px;
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.topbar-icon-btn {
  display: flex; align-items: center; justify-content: center;
  width: 34px; height: 34px;
  border-radius: var(--radius);
  color: var(--text-muted);
  transition: background var(--transition), color var(--transition);
  cursor: pointer;
  position: relative;
}
.topbar-icon-btn:hover { background: var(--bg-elevated); color: var(--text-primary); }

.notif-dot {
  position: absolute;
  top: 7px; right: 7px;
  width: 6px; height: 6px;
  background: var(--red);
  border-radius: 50%;
  border: 1.5px solid var(--bg-surface);
}

.topbar-avatar {
  display: flex; align-items: center; justify-content: center;
  width: 32px; height: 32px;
  border-radius: 50%;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
  cursor: pointer;
  transition: border-color var(--transition);
}
.topbar-avatar:hover { border-color: var(--text-muted); }

@media (max-width: 600px) {
  .topbar-search-btn span, .topbar-search-btn kbd { display: none; }
  .topbar-search-btn { padding: 7px; }
}
</style>
