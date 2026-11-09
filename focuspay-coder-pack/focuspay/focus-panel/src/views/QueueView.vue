<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Очередь</h1>
        <p class="page-subtitle">{{ waiting }} ожидают · {{ inProgress }} в работе</p>
      </div>
      <div style="display:flex;gap:8px">
        <AppButton variant="secondary" size="sm">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1v6l4 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.5"/></svg>
          Время ожидания
        </AppButton>
        <AppButton variant="primary" size="sm">Принять следующего</AppButton>
      </div>
    </div>

    <!-- Summary row -->
    <div class="grid-3">
      <div class="stat-card" v-for="s in stats" :key="s.label">
        <div class="stat-value">{{ s.value }}</div>
        <div class="stat-label">{{ s.label }}</div>
        <div class="stat-bar"><div class="stat-fill" :style="{ width: s.pct + '%', background: s.color }" /></div>
      </div>
    </div>

    <!-- Queue list -->
    <div class="queue-board">
      <div class="queue-col" v-for="col in columns" :key="col.key">
        <div class="queue-col-head">
          <span>{{ col.label }}</span>
          <AppBadge :variant="col.badgeVariant" size="sm">{{ col.items.length }}</AppBadge>
        </div>
        <div class="queue-cards">
          <div class="queue-card" v-for="item in col.items" :key="item.id">
            <div class="qcard-top">
              <div class="qcard-avatar">{{ item.initials }}</div>
              <div class="qcard-info">
                <div class="qcard-name">{{ item.name }}</div>
                <div class="qcard-service">{{ item.service }}</div>
              </div>
              <AppBadge :variant="item.priority === 'высокий' ? 'orange' : 'default'" size="sm">
                {{ item.priority }}
              </AppBadge>
            </div>
            <div class="qcard-meta">
              <span>
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><circle cx="6" cy="6" r="5" stroke="currentColor" stroke-width="1.3"/><path d="M6 3.5v3l1.5 1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
                {{ item.wait }}
              </span>
              <span>#{{ item.id }}</span>
            </div>
            <div class="qcard-actions">
              <AppButton variant="secondary" size="sm" style="flex:1">Принять</AppButton>
              <AppButton variant="ghost" size="sm" :icon-only="true">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="3" r="1"/><circle cx="7" cy="7" r="1"/><circle cx="7" cy="11" r="1"/></svg>
              </AppButton>
            </div>
          </div>
          <div v-if="!col.items.length" class="queue-empty">Пусто</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppBadge from '@/components/ui/AppBadge.vue'

const waiting = 8
const inProgress = 3

const stats = [
  { label: 'Ожидают', value: '8', pct: 62, color: 'var(--yellow)' },
  { label: 'В обработке', value: '3', pct: 23, color: 'var(--blue)' },
  { label: 'Завершено сегодня', value: '34', pct: 100, color: 'var(--green)' },
]

const columns = [
  {
    key: 'waiting', label: 'Ожидают', badgeVariant: 'yellow' as const,
    items: [
      { id: '1044', initials: 'АК', name: 'Алексей Крылов', service: 'Вывод средств', wait: '3 мин', priority: 'высокий' },
      { id: '1047', initials: 'НВ', name: 'Надежда Власова', service: 'Консультация', wait: '7 мин', priority: 'обычный' },
      { id: '1048', initials: 'СМ', name: 'Сергей Морозов', service: 'Перевод', wait: '12 мин', priority: 'обычный' },
      { id: '1049', initials: 'ЛП', name: 'Людмила Павлова', service: 'Пополнение', wait: '15 мин', priority: 'обычный' },
    ],
  },
  {
    key: 'inprogress', label: 'В работе', badgeVariant: 'blue' as const,
    items: [
      { id: '1040', initials: 'ВС', name: 'Владимир Соколов', service: 'Вывод', wait: '22 мин', priority: 'высокий' },
      { id: '1041', initials: 'ТК', name: 'Татьяна Козлова', service: 'Консультация', wait: '18 мин', priority: 'обычный' },
      { id: '1043', initials: 'АС', name: 'Анна Сидорова', service: 'Пополнение', wait: '9 мин', priority: 'обычный' },
    ],
  },
  {
    key: 'done', label: 'Завершено', badgeVariant: 'green' as const,
    items: [
      { id: '1042', initials: 'ИП', name: 'Иван Петров', service: 'Вывод', wait: '8 мин', priority: 'обычный' },
      { id: '1039', initials: 'ДН', name: 'Дмитрий Новиков', service: 'Перевод', wait: '5 мин', priority: 'обычный' },
    ],
  },
]
</script>

<style scoped>
.stat-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
}
.stat-value { font-size: 28px; font-weight: 800; letter-spacing: -1px; color: var(--text-primary); }
.stat-label { font-size: 12px; color: var(--text-muted); margin: 4px 0 12px; }
.stat-bar { height: 3px; background: var(--bg-elevated); border-radius: 2px; overflow: hidden; }
.stat-fill { height: 100%; border-radius: 2px; transition: width 0.5s ease; }

.queue-board {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 900px) { .queue-board { grid-template-columns: 1fr; } }

.queue-col-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px;
  font-size: 13px; font-weight: 600; color: var(--text-primary);
}

.queue-cards { display: flex; flex-direction: column; gap: 8px; }

.queue-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 14px;
  display: flex; flex-direction: column; gap: 10px;
  transition: border-color var(--transition);
}
.queue-card:hover { border-color: var(--border-strong); }

.qcard-top { display: flex; align-items: center; gap: 10px; }
.qcard-avatar {
  width: 34px; height: 34px; border-radius: 50%;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: var(--text-secondary);
  flex-shrink: 0;
}
.qcard-info { flex: 1; min-width: 0; }
.qcard-name { font-size: 13px; font-weight: 500; color: var(--text-primary); }
.qcard-service { font-size: 11.5px; color: var(--text-muted); margin-top: 1px; }

.qcard-meta {
  display: flex; justify-content: space-between;
  font-size: 11.5px; color: var(--text-muted);
}
.qcard-meta span { display: flex; align-items: center; gap: 4px; }

.qcard-actions { display: flex; gap: 6px; }

.queue-empty {
  text-align: center; padding: 28px 12px;
  font-size: 12.5px; color: var(--text-muted);
  border: 1px dashed var(--border);
  border-radius: var(--radius-lg);
}
</style>
