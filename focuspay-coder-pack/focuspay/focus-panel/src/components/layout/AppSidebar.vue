<template>
  <aside class="sidebar" :class="{ 'sidebar--collapsed': collapsed }">
    <!-- Logo -->
    <div class="sidebar-logo">
      <div class="logo-icon">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <rect width="18" height="18" rx="5" fill="white"/>
          <path d="M4 6h10M4 9h7M4 12h8" stroke="#0a0a0a" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
      </div>
      <Transition name="fade">
        <span v-if="!collapsed" class="logo-text">FocusPanel</span>
      </Transition>
    </div>

    <!-- Navigation -->
    <nav class="sidebar-nav" aria-label="Навигация">
      <div class="nav-section">
        <p v-if="!collapsed" class="nav-label">Основное</p>
        <RouterLink
          v-for="item in mainNav"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :title="collapsed ? item.label : undefined"
          active-class="nav-item--active"
        >
          <span class="nav-icon" v-html="item.icon" aria-hidden="true" />
          <Transition name="fade">
            <span v-if="!collapsed" class="nav-label-text">{{ item.label }}</span>
          </Transition>
          <Transition name="fade">
            <span v-if="!collapsed && item.badge" class="nav-badge">{{ item.badge }}</span>
          </Transition>
        </RouterLink>
      </div>

      <div class="nav-section">
        <p v-if="!collapsed" class="nav-label">Финансы</p>
        <RouterLink
          v-for="item in financeNav"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :title="collapsed ? item.label : undefined"
          active-class="nav-item--active"
        >
          <span class="nav-icon" v-html="item.icon" aria-hidden="true" />
          <Transition name="fade">
            <span v-if="!collapsed" class="nav-label-text">{{ item.label }}</span>
          </Transition>
        </RouterLink>
      </div>

      <div class="nav-section">
        <p v-if="!collapsed" class="nav-label">Управление</p>
        <RouterLink
          v-for="item in mgmtNav"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :title="collapsed ? item.label : undefined"
          active-class="nav-item--active"
        >
          <span class="nav-icon" v-html="item.icon" aria-hidden="true" />
          <Transition name="fade">
            <span v-if="!collapsed" class="nav-label-text">{{ item.label }}</span>
          </Transition>
        </RouterLink>
      </div>
    </nav>

    <!-- Collapse toggle -->
    <button class="sidebar-toggle" @click="emit('toggle')" :aria-label="collapsed ? 'Развернуть' : 'Свернуть'">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" :style="collapsed ? 'transform:rotate(180deg)' : ''">
        <path d="M9 2L4 7l5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <Transition name="fade">
        <span v-if="!collapsed">Свернуть</span>
      </Transition>
    </button>
  </aside>
</template>

<script setup lang="ts">
defineProps<{ collapsed: boolean }>()
const emit = defineEmits<{ (e: 'toggle'): void }>()

const mainNav = [
  {
    to: '/',
    label: 'Дашборд',
    icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="6" height="6" rx="1.5" stroke="currentColor" stroke-width="1.5"/><rect x="9" y="1" width="6" height="6" rx="1.5" stroke="currentColor" stroke-width="1.5"/><rect x="1" y="9" width="6" height="6" rx="1.5" stroke="currentColor" stroke-width="1.5"/><rect x="9" y="9" width="6" height="6" rx="1.5" stroke="currentColor" stroke-width="1.5"/></svg>`,
  },
  {
    to: '/requests',
    label: 'Заявки',
    icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M2 8h8M2 12h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    badge: '12',
  },
  {
    to: '/queue',
    label: 'Очередь',
    icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.5"/><path d="M8 5v3.5l2.5 1.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  },
  {
    to: '/search',
    label: 'Поиск',
    icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.5"/><path d="M10 10l3.5 3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  },
  {
    to: '/create',
    label: 'Создать',
    icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 2v12M2 8h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  },
]

const financeNav = [
  {
    to: '/output',
    label: 'Вывод средств',
    icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="1.5" y="3.5" width="13" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/><path d="M1.5 6.5h13" stroke="currentColor" stroke-width="1.5"/></svg>`,
  },
  {
    to: '/promos',
    label: 'Промокоды',
    icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 8.5L7.5 3l1 1-1 1 1 1 1-1 1 1-5.5 5.5-1-1 1-1-1-1-1 1-1-1z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><circle cx="12" cy="4" r="1.5" stroke="currentColor" stroke-width="1.3"/></svg>`,
  },
]

const mgmtNav = [
  {
    to: '/shifts',
    label: 'Смены',
    icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="2" y="3" width="12" height="11" rx="1.5" stroke="currentColor" stroke-width="1.5"/><path d="M5 1v4M11 1v4M2 7h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  },
  {
    to: '/chat',
    label: 'Чат',
    icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 2h12a1 1 0 011 1v7a1 1 0 01-1 1H5l-3 3V3a1 1 0 011-1z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
  },
]
</script>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: var(--sidebar-w);
  min-height: 100vh;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  transition: width var(--transition-slow);
  flex-shrink: 0;
  position: relative;
  z-index: 10;
}
.sidebar--collapsed { width: 60px; }

/* Logo */
.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  height: var(--topbar-h);
  border-bottom: 1px solid var(--border);
  overflow: hidden;
  flex-shrink: 0;
}
.logo-icon {
  display: flex; align-items: center; justify-content: center;
  width: 30px; height: 30px;
  background: var(--text-primary);
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}
.logo-text {
  font-size: 14.5px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.3px;
  white-space: nowrap;
}

/* Nav */
.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 8px;
  overflow-y: auto;
  overflow-x: hidden;
}

.nav-section {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-bottom: 12px;
  margin-bottom: 4px;
  border-bottom: 1px solid var(--border);
}
.nav-section:last-child { border-bottom: none; padding-bottom: 0; }

.nav-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.8px;
  text-transform: uppercase;
  padding: 0 6px 6px;
  white-space: nowrap;
  overflow: hidden;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 8px;
  border-radius: var(--radius);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  transition: background var(--transition), color var(--transition);
  white-space: nowrap;
  overflow: hidden;
  text-decoration: none;
  position: relative;
}
.nav-item:hover { background: var(--bg-elevated); color: var(--text-primary); }
.nav-item--active { background: var(--bg-elevated); color: var(--text-primary); }
.nav-item--active::before {
  content: '';
  position: absolute;
  left: 0; top: 6px; bottom: 6px;
  width: 3px;
  background: var(--text-primary);
  border-radius: 0 2px 2px 0;
}

.nav-icon { display: flex; align-items: center; flex-shrink: 0; width: 16px; }
.nav-label-text { overflow: hidden; text-overflow: ellipsis; }

.nav-badge {
  margin-left: auto;
  background: var(--bg-overlay);
  border: 1px solid var(--border-strong);
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 600;
  padding: 0 6px;
  border-radius: 10px;
  flex-shrink: 0;
}

/* Toggle */
.sidebar-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: color var(--transition);
  white-space: nowrap;
  overflow: hidden;
}
.sidebar-toggle:hover { color: var(--text-primary); }

/* Transitions */
.fade-enter-active, .fade-leave-active { transition: opacity 150ms ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
