<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Смены</h1>
        <p class="page-subtitle">Управление рабочим расписанием</p>
      </div>
      <div style="display:flex;gap:8px">
        <AppButton variant="secondary" size="sm">Экспорт</AppButton>
        <AppButton variant="primary" size="sm" @click="showModal = true">
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M6.5 1v11M1 6.5h11" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
          Добавить смену
        </AppButton>
      </div>
    </div>

    <!-- Week selector -->
    <div class="week-nav card">
      <button class="week-btn" @click="weekOffset--">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M9 2L4 7l5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
      <span class="week-label">{{ weekLabel }}</span>
      <button class="week-btn" @click="weekOffset++">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M5 2l5 5-5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
      <button class="week-today" @click="weekOffset = 0">Сегодня</button>
    </div>

    <!-- Calendar grid -->
    <div class="shifts-calendar">
      <div class="cal-header">
        <div class="cal-row-label" />
        <div class="cal-day-head" v-for="(d, i) in weekDays" :key="i" :class="{ 'cal-day-head--today': d.isToday }">
          <span class="cal-day-name">{{ d.name }}</span>
          <span class="cal-day-num">{{ d.num }}</span>
        </div>
      </div>

      <div class="cal-row" v-for="op in operators" :key="op.name">
        <div class="cal-row-label">
          <div class="op-avatar">{{ op.initials }}</div>
          <div class="op-info">
            <div class="op-name">{{ op.name }}</div>
            <div class="op-role">{{ op.role }}</div>
          </div>
        </div>
        <div
          class="cal-cell"
          v-for="(d, di) in weekDays"
          :key="di"
          :class="{ 'cal-cell--today': d.isToday }"
        >
          <div
            v-if="getShift(op.name, di)"
            class="shift-pill"
            :class="`shift-pill--${getShift(op.name, di)!.type}`"
          >
            {{ getShift(op.name, di)!.time }}
          </div>
        </div>
      </div>
    </div>

    <!-- Summary table -->
    <div class="card">
      <div class="card-head" style="margin-bottom:14px">
        <span class="card-heading">Сводка по операторам</span>
      </div>
      <AppTable :columns="sumCols" :rows="summary">
        <template #status="{ value }">
          <AppBadge :variant="value === 'Активна' ? 'green' : value === 'Перерыв' ? 'yellow' : 'default'">{{ value }}</AppBadge>
        </template>
        <template #hours="{ value }">
          <span class="font-mono">{{ value }}ч</span>
        </template>
      </AppTable>
    </div>

    <!-- Add shift modal -->
    <AppModal v-model="showModal" title="Новая смена" subtitle="Добавить рабочую смену оператору">
      <AppSelect v-model="newShift.operator" label="Оператор" :options="operatorOptions" placeholder="Выберите оператора" />
      <div class="grid-2">
        <AppInput v-model="newShift.date" label="Дата" type="date" />
        <AppSelect v-model="newShift.type" label="Тип смены" :options="shiftTypes" placeholder="Тип" />
      </div>
      <div class="grid-2">
        <AppInput v-model="newShift.start" label="Начало" type="time" />
        <AppInput v-model="newShift.end" label="Конец" type="time" />
      </div>
      <template #footer>
        <AppButton variant="ghost" @click="showModal = false">Отмена</AppButton>
        <AppButton variant="primary" @click="addShift">Добавить</AppButton>
      </template>
    </AppModal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppTable from '@/components/ui/AppTable.vue'
import AppModal from '@/components/ui/AppModal.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'

const showModal = ref(false)
const weekOffset = ref(0)

const weekDays = computed(() => {
  const names = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
  const today = new Date()
  const dayOfWeek = (today.getDay() + 6) % 7
  const monday = new Date(today)
  monday.setDate(today.getDate() - dayOfWeek + weekOffset.value * 7)
  return names.map((name, i) => {
    const d = new Date(monday)
    d.setDate(monday.getDate() + i)
    return { name, num: d.getDate(), isToday: d.toDateString() === today.toDateString() }
  })
})

const weekLabel = computed(() => {
  const days = weekDays.value
  return `${days[0].num} — ${days[6].num} июня 2026`
})

const operators = [
  { name: 'Елена Громова', initials: 'ЕГ', role: 'Оператор' },
  { name: 'Роман Фёдоров', initials: 'РФ', role: 'Старший оператор' },
  { name: 'Ирина Захарова', initials: 'ИЗ', role: 'Оператор' },
  { name: 'Михаил Алексеев', initials: 'МА', role: 'Оператор' },
]

const shifts: Record<string, { time: string; type: string }[]> = {
  'Елена Громова':   [{ time: '09–18', type: 'day' }, { time: '09–18', type: 'day' }, null!, null!, { time: '09–18', type: 'day' }, null!, null!],
  'Роман Фёдоров':   [null!, { time: '12–21', type: 'evening' }, { time: '12–21', type: 'evening' }, { time: '12–21', type: 'evening' }, null!, null!, null!],
  'Ирина Захарова':  [{ time: '14–23', type: 'night' }, null!, { time: '14–23', type: 'night' }, null!, { time: '14–23', type: 'night' }, null!, null!],
  'Михаил Алексеев': [null!, null!, { time: '09–18', type: 'day' }, { time: '09–18', type: 'day' }, { time: '09–18', type: 'day' }, { time: '09–18', type: 'day' }, null!],
}

function getShift(name: string, dayIdx: number) {
  return shifts[name]?.[dayIdx] ?? null
}

const sumCols = [
  { key: 'name', label: 'Оператор' },
  { key: 'role', label: 'Должность' },
  { key: 'hours', label: 'Часов', width: '80px' },
  { key: 'shifts', label: 'Смен', width: '70px' },
  { key: 'status', label: 'Статус', width: '110px' },
]

const summary = [
  { name: 'Елена Громова', role: 'Оператор', hours: 24, shifts: 3, status: 'Активна' },
  { name: 'Роман Фёдоров', role: 'Старший оператор', hours: 27, shifts: 3, status: 'Перерыв' },
  { name: 'Ирина Захарова', role: 'Оператор', hours: 27, shifts: 3, status: 'Активна' },
  { name: 'Михаил Алексеев', role: 'Оператор', hours: 36, shifts: 4, status: 'Выходной' },
]

const operatorOptions = operators.map(o => ({ value: o.name, label: o.name }))
const shiftTypes = [
  { value: 'day', label: 'Дневная (09–18)' },
  { value: 'evening', label: 'Вечерняя (12–21)' },
  { value: 'night', label: 'Ночная (14–23)' },
]

const newShift = ref({ operator: '', date: '', type: '', start: '', end: '' })

function addShift() {
  showModal.value = false
  newShift.value = { operator: '', date: '', type: '', start: '', end: '' }
}
</script>

<style scoped>
.card-head { display: flex; align-items: center; justify-content: space-between; }
.card-heading { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }

/* Week nav */
.week-nav {
  display: flex; align-items: center; gap: 12px; padding: 10px 16px;
}
.week-btn {
  display: flex; align-items: center; justify-content: center;
  width: 30px; height: 30px;
  border-radius: var(--radius-sm);
  color: var(--text-muted); cursor: pointer;
  transition: background var(--transition), color var(--transition);
}
.week-btn:hover { background: var(--bg-elevated); color: var(--text-primary); }
.week-label { font-size: 13.5px; font-weight: 600; color: var(--text-primary); flex: 1; text-align: center; }
.week-today {
  font-size: 12px; color: var(--text-muted); padding: 4px 10px;
  border-radius: var(--radius-sm); cursor: pointer;
  border: 1px solid var(--border);
  transition: all var(--transition);
}
.week-today:hover { border-color: var(--border-strong); color: var(--text-primary); }

/* Calendar */
.shifts-calendar {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.cal-header {
  display: grid;
  grid-template-columns: 200px repeat(7, 1fr);
  border-bottom: 1px solid var(--border);
}

.cal-day-head {
  padding: 10px 8px;
  text-align: center;
  border-left: 1px solid var(--border);
}
.cal-day-head--today { background: rgba(255,255,255,0.03); }
.cal-day-name { display: block; font-size: 10px; font-weight: 600; color: var(--text-muted); letter-spacing: 0.5px; text-transform: uppercase; }
.cal-day-num { display: block; font-size: 14px; font-weight: 700; color: var(--text-primary); margin-top: 2px; }
.cal-day-head--today .cal-day-num { color: var(--accent); }

.cal-row {
  display: grid;
  grid-template-columns: 200px repeat(7, 1fr);
  border-top: 1px solid var(--border);
}

.cal-row-label {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px;
}
.op-avatar {
  width: 30px; height: 30px; border-radius: 50%;
  background: var(--bg-elevated); border: 1px solid var(--border-strong);
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700; color: var(--text-secondary);
  flex-shrink: 0;
}
.op-name { font-size: 12.5px; font-weight: 500; color: var(--text-primary); }
.op-role { font-size: 11px; color: var(--text-muted); }

.cal-cell {
  border-left: 1px solid var(--border);
  padding: 6px;
  display: flex; align-items: center; justify-content: center;
}
.cal-cell--today { background: rgba(255,255,255,0.02); }

.shift-pill {
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  font-size: 10.5px; font-weight: 600;
  white-space: nowrap;
}
.shift-pill--day     { background: var(--blue-bg); color: var(--blue); }
.shift-pill--evening { background: var(--purple-bg); color: var(--purple); }
.shift-pill--night   { background: var(--orange-bg); color: var(--orange); }

@media (max-width: 1000px) {
  .shifts-calendar { overflow-x: auto; }
  .cal-header, .cal-row { min-width: 700px; }
}
</style>
