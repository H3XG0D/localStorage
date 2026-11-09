<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Поиск</h1>
        <p class="page-subtitle">Поиск по клиентам, заявкам и транзакциям</p>
      </div>
    </div>

    <!-- Big search input -->
    <div class="search-hero">
      <div class="search-input-wrap">
        <svg class="search-ico" width="18" height="18" viewBox="0 0 18 18" fill="none">
          <circle cx="7.5" cy="7.5" r="5.5" stroke="currentColor" stroke-width="1.8"/>
          <path d="M13 13l4 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        <input
          v-model="query"
          class="search-field"
          placeholder="Введите имя, ID, телефон или сумму..."
          type="search"
          autofocus
          @input="doSearch"
        />
        <kbd class="search-esc" v-if="query" @click="query = ''">Esc</kbd>
      </div>

      <!-- Type filters -->
      <div class="search-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="search-tab"
          :class="{ 'search-tab--active': activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
          <span class="tab-count" v-if="tab.count">{{ tab.count }}</span>
        </button>
      </div>
    </div>

    <!-- Results -->
    <div v-if="!query" class="search-empty">
      <svg width="40" height="40" viewBox="0 0 40 40" fill="none"><circle cx="18" cy="18" r="13" stroke="currentColor" stroke-width="2"/><path d="M30 30l8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
      <p>Начните вводить запрос для поиска</p>
    </div>

    <template v-else-if="results.length">
      <div class="results-grid">
        <div class="result-card" v-for="r in results" :key="r.id" @click="openResult(r)">
          <div class="result-icon">
            <span v-html="r.icon" />
          </div>
          <div class="result-body">
            <div class="result-title">{{ r.title }}</div>
            <div class="result-sub">{{ r.sub }}</div>
          </div>
          <div class="result-right">
            <AppBadge :variant="r.badgeVariant">{{ r.badge }}</AppBadge>
            <span class="result-meta">{{ r.meta }}</span>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="search-empty">
      <p>По запросу «{{ query }}» ничего не найдено</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import AppBadge from '@/components/ui/AppBadge.vue'

const query = ref('')
const activeTab = ref('all')

const tabs = [
  { key: 'all', label: 'Всё', count: 0 },
  { key: 'clients', label: 'Клиенты', count: 0 },
  { key: 'requests', label: 'Заявки', count: 0 },
]

const allData = [
  { id: 'c1', type: 'client', title: 'Иван Петров', sub: '+7 (916) 123-45-67 · ivan.petrov@mail.ru', badge: 'Клиент', badgeVariant: 'blue' as const, meta: '12 заявок', icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 8a3 3 0 100-6 3 3 0 000 6zM2 14c0-2.21 2.686-4 6-4s6 1.79 6 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>` },
  { id: 'c2', type: 'client', title: 'Анна Сидорова', sub: '+7 (903) 987-65-43 · a.sidorova@gmail.com', badge: 'Клиент', badgeVariant: 'blue' as const, meta: '5 заявок', icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 8a3 3 0 100-6 3 3 0 000 6zM2 14c0-2.21 2.686-4 6-4s6 1.79 6 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>` },
  { id: 'r1', type: 'request', title: 'Заявка #1042 — Иван Петров', sub: 'Вывод · ₽ 5 000', badge: 'Выполнено', badgeVariant: 'green' as const, meta: '29.06', icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M2 8h8M2 12h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>` },
  { id: 'r2', type: 'request', title: 'Заявка #1043 — Анна Сидорова', sub: 'Пополнение · ₽ 12 000', badge: 'В работе', badgeVariant: 'blue' as const, meta: '28.06', icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M2 8h8M2 12h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>` },
  { id: 'c3', type: 'client', title: 'Олег Кузнецов', sub: '+7 (926) 555-12-34 · o.kuznetsov@yandex.ru', badge: 'Клиент', badgeVariant: 'blue' as const, meta: '3 заявки', icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 8a3 3 0 100-6 3 3 0 000 6zM2 14c0-2.21 2.686-4 6-4s6 1.79 6 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>` },
  { id: 'r3', type: 'request', title: 'Заявка #1041 — Светлана Орлова', sub: 'Перевод · ₽ 22 000', badge: 'Выполнено', badgeVariant: 'green' as const, meta: '27.06', icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M2 8h8M2 12h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>` },
]

const results = computed(() => {
  if (!query.value) return []
  const q = query.value.toLowerCase()
  return allData.filter(d => {
    const matchType = activeTab.value === 'all' || (activeTab.value === 'clients' && d.type === 'client') || (activeTab.value === 'requests' && d.type === 'request')
    return matchType && (d.title.toLowerCase().includes(q) || d.sub.toLowerCase().includes(q))
  })
})

function doSearch() {
  tabs[0].count = results.value.length
}

function openResult(r: any) {
  console.log('open', r)
}
</script>

<style scoped>
.search-hero {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  overflow: hidden;
}

.search-input-wrap {
  display: flex; align-items: center; gap: 12px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--border);
}

.search-ico { color: var(--text-muted); flex-shrink: 0; }

.search-field {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  font-size: 16px;
  color: var(--text-primary);
}
.search-field::placeholder { color: var(--text-muted); }

.search-esc {
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: 5px;
  padding: 2px 7px;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
}

.search-tabs {
  display: flex;
  gap: 2px;
  padding: 8px 12px;
}

.search-tab {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 12px;
  border-radius: var(--radius);
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-muted);
  cursor: pointer;
  transition: background var(--transition), color var(--transition);
}
.search-tab:hover { background: var(--bg-elevated); color: var(--text-primary); }
.search-tab--active { background: var(--bg-elevated); color: var(--text-primary); }

.tab-count {
  background: var(--bg-overlay);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0 6px;
  font-size: 10.5px;
}

.search-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; padding: 64px 20px;
  color: var(--text-muted); font-size: 13.5px;
}

.results-grid { display: flex; flex-direction: column; gap: 4px; }

.result-card {
  display: flex; align-items: center; gap: 14px;
  padding: 12px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: border-color var(--transition), background var(--transition);
}
.result-card:hover { border-color: var(--border-strong); background: var(--bg-elevated); }

.result-icon {
  width: 36px; height: 36px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  display: flex; align-items: center; justify-content: center;
  color: var(--text-muted); flex-shrink: 0;
}

.result-body { flex: 1; min-width: 0; }
.result-title { font-size: 13.5px; font-weight: 500; color: var(--text-primary); }
.result-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

.result-right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex-shrink: 0; }
.result-meta { font-size: 11.5px; color: var(--text-muted); }
</style>
