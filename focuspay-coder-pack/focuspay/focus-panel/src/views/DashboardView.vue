<template>
  <div class="page">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">Дашборд</h1>
        <p class="page-subtitle">Сводка за сегодня, {{ today }}</p>
      </div>
      <AppButton variant="primary" size="sm" @click="$router.push('/create')">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M6.5 1v11M1 6.5h11" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        Новая заявка
      </AppButton>
    </div>

    <!-- KPI cards -->
    <div class="grid-4">
      <div class="kpi-card" v-for="kpi in kpis" :key="kpi.label">
        <div class="kpi-top">
          <span class="kpi-icon" v-html="kpi.icon" />
          <AppBadge :variant="kpi.trend > 0 ? 'green' : 'red'" size="sm">
            {{ kpi.trend > 0 ? '+' : '' }}{{ kpi.trend }}%
          </AppBadge>
        </div>
        <div class="kpi-value">{{ kpi.value }}</div>
        <div class="kpi-label">{{ kpi.label }}</div>
      </div>
    </div>

    <!-- Recent requests + Queue status -->
    <div class="dash-grid">
      <!-- Recent requests -->
      <div class="card">
        <div class="card-head">
          <span class="card-heading">Последние заявки</span>
          <RouterLink to="/requests" class="card-link">Все заявки →</RouterLink>
        </div>
        <AppTable :columns="reqCols" :rows="recentRequests">
          <template #status="{ value }">
            <AppBadge :variant="statusVariant(value)">{{ value }}</AppBadge>
          </template>
          <template #amount="{ value }">
            <span class="font-mono">{{ value }}</span>
          </template>
        </AppTable>
      </div>

      <!-- Right column -->
      <div class="dash-right">
        <!-- Queue -->
        <div class="card">
          <div class="card-head">
            <span class="card-heading">Очередь</span>
            <RouterLink to="/queue" class="card-link">Открыть →</RouterLink>
          </div>
          <div class="queue-list">
            <div class="queue-item" v-for="q in queueItems" :key="q.id">
              <div class="queue-avatar">{{ q.initials }}</div>
              <div class="queue-info">
                <div class="queue-name">{{ q.name }}</div>
                <div class="queue-meta">{{ q.service }} · {{ q.wait }}</div>
              </div>
              <AppBadge :variant="q.priority === 'высокий' ? 'orange' : 'default'" size="sm">
                {{ q.priority }}
              </AppBadge>
            </div>
          </div>
        </div>

        <!-- Active shifts -->
        <div class="card">
          <div class="card-head">
            <span class="card-heading">Активные смены</span>
            <RouterLink to="/shifts" class="card-link">Все →</RouterLink>
          </div>
          <div class="shift-list">
            <div class="shift-item" v-for="s in activeShifts" :key="s.name">
              <div class="shift-dot" :class="`shift-dot--${s.status}`" />
              <div class="shift-info">
                <div class="shift-name">{{ s.name }}</div>
                <div class="shift-role">{{ s.role }}</div>
              </div>
              <span class="shift-time">{{ s.time }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppTable from '@/components/ui/AppTable.vue'

const today = computed(() => new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' }))

const kpis = [
  { label: 'Новых заявок', value: '47', trend: 12, icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M2 8h8M2 12h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>` },
  { label: 'В очереди', value: '13', trend: -5, icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.5"/><path d="M8 5v3.5l2.5 1.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>` },
  { label: 'Выведено (₽)', value: '128 400', trend: 8, icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="1.5" y="3.5" width="13" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/><path d="M1.5 6.5h13" stroke="currentColor" stroke-width="1.5"/></svg>` },
  { label: 'Активные смены', value: '6', trend: 0, icon: `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 2a4 4 0 100 8A4 4 0 008 2zM2 14c0-2.21 2.686-4 6-4s6 1.79 6 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>` },
]

const reqCols = [
  { key: 'id', label: '#', width: '60px' },
  { key: 'client', label: 'Клиент' },
  { key: 'service', label: 'Услуга' },
  { key: 'amount', label: 'Сумма', width: '100px' },
  { key: 'status', label: 'Статус', width: '110px' },
]

const recentRequests = [
  { id: '1042', client: 'Иван Петров', service: 'Вывод', amount: '₽ 5 000', status: 'Выполнено' },
  { id: '1043', client: 'Анна Сидорова', service: 'Пополнение', amount: '₽ 12 000', status: 'В работе' },
  { id: '1044', client: 'Олег Кузнецов', service: 'Консультация', amount: '—', status: 'Ожидает' },
  { id: '1045', client: 'Мария Белова', service: 'Вывод', amount: '₽ 3 200', status: 'Отклонено' },
  { id: '1046', client: 'Дмитрий Новиков', service: 'Перевод', amount: '₽ 8 750', status: 'Выполнено' },
]

function statusVariant(s: string) {
  if (s === 'Выполнено') return 'green'
  if (s === 'В работе') return 'blue'
  if (s === 'Отклонено') return 'red'
  return 'default'
}

const queueItems = [
  { id: 1, initials: 'АК', name: 'Алексей Крылов', service: 'Вывод', wait: '3 мин', priority: 'высокий' },
  { id: 2, initials: 'НВ', name: 'Надежда Власова', service: 'Консультация', wait: '7 мин', priority: 'обычный' },
  { id: 3, initials: 'СМ', name: 'Сергей Морозов', service: 'Перевод', wait: '12 мин', priority: 'обычный' },
]

const activeShifts = [
  { name: 'Елена Громова', role: 'Оператор', time: '09:00 – 18:00', status: 'active' },
  { name: 'Роман Фёдоров', role: 'Старший оператор', time: '12:00 – 21:00', status: 'active' },
  { name: 'Ирина Захарова', role: 'Оператор', time: '14:00 – 23:00', status: 'break' },
]
</script>

<style scoped>
.kpi-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color var(--transition);
}
.kpi-card:hover { border-color: var(--border-strong); }

.kpi-top { display: flex; align-items: center; justify-content: space-between; }
.kpi-icon { color: var(--text-muted); display: flex; }
.kpi-value { font-size: 26px; font-weight: 800; letter-spacing: -0.8px; color: var(--text-primary); font-variant-numeric: tabular-nums; }
.kpi-label { font-size: 12px; color: var(--text-muted); }

.dash-grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 16px;
  align-items: start;
}
@media (max-width: 1100px) { .dash-grid { grid-template-columns: 1fr; } }

.dash-right { display: flex; flex-direction: column; gap: 16px; }

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.card-heading { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.card-link { font-size: 12px; color: var(--text-muted); transition: color var(--transition); }
.card-link:hover { color: var(--text-primary); }

/* Queue */
.queue-list { display: flex; flex-direction: column; gap: 8px; }
.queue-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px;
  background: var(--bg-elevated);
  border-radius: var(--radius);
}
.queue-avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  background: var(--bg-overlay);
  border: 1px solid var(--border-strong);
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: var(--text-secondary);
  flex-shrink: 0;
}
.queue-info { flex: 1; min-width: 0; }
.queue-name { font-size: 13px; font-weight: 500; color: var(--text-primary); }
.queue-meta { font-size: 11px; color: var(--text-muted); margin-top: 1px; }

/* Shifts */
.shift-list { display: flex; flex-direction: column; gap: 8px; }
.shift-item {
  display: flex; align-items: center; gap: 10px;
  padding: 4px 0;
}
.shift-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.shift-dot--active { background: var(--green); box-shadow: 0 0 0 3px var(--green-bg); }
.shift-dot--break  { background: var(--yellow); box-shadow: 0 0 0 3px var(--yellow-bg); }
.shift-info { flex: 1; min-width: 0; }
.shift-name { font-size: 13px; font-weight: 500; color: var(--text-primary); }
.shift-role { font-size: 11px; color: var(--text-muted); margin-top: 1px; }
.shift-time { font-size: 11.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
