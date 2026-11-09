<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Вывод средств</h1>
        <p class="page-subtitle">Управление заявками на вывод</p>
      </div>
      <div style="display:flex;gap:8px">
        <AppButton variant="secondary" size="sm">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1v8M4 6l3 3 3-3M2 11h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          Экспорт
        </AppButton>
        <AppButton variant="primary" size="sm" @click="showModal = true">Новая заявка</AppButton>
      </div>
    </div>

    <!-- KPI row -->
    <div class="grid-4">
      <div class="kpi-card" v-for="k in kpis" :key="k.label">
        <div class="kpi-label">{{ k.label }}</div>
        <div class="kpi-val">{{ k.value }}</div>
        <AppBadge :variant="k.trend > 0 ? 'green' : 'red'" size="sm">{{ k.trend > 0 ? '+' : '' }}{{ k.trend }}%</AppBadge>
      </div>
    </div>

    <!-- Filters -->
    <div class="card" style="padding:14px 16px">
      <div class="filters-row">
        <AppInput v-model="search" placeholder="Поиск по клиенту, ID..." type="search">
          <template #prefix>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4" stroke="currentColor" stroke-width="1.4"/><path d="M10 10l3 3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
          </template>
        </AppInput>
        <AppSelect v-model="filterStatus" :options="statusOptions" placeholder="Все статусы" />
        <AppSelect v-model="filterMethod" :options="methodOptions" placeholder="Все методы" />
        <AppButton variant="ghost" size="sm" @click="resetFilters">Сбросить</AppButton>
      </div>
    </div>

    <!-- Table -->
    <AppTable :columns="cols" :rows="filtered" empty-text="Заявки на вывод не найдены">
      <template #id="{ value }">
        <span class="font-mono text-muted">#{{ value }}</span>
      </template>
      <template #amount="{ value }">
        <span class="font-mono" style="font-weight:600">{{ value }}</span>
      </template>
      <template #status="{ value }">
        <AppBadge :variant="statusVariant(value)">{{ value }}</AppBadge>
      </template>
      <template #method="{ value }">
        <div class="method-cell">
          <span class="method-icon" v-html="methodIcon(value)" />
          <span>{{ value }}</span>
        </div>
      </template>
      <template #actions="{ row }">
        <div class="row-actions">
          <AppButton
            v-if="row.status === 'Ожидает'"
            variant="secondary"
            size="sm"
            @click.stop="approve(row)"
          >
            Принять
          </AppButton>
          <AppButton
            v-if="row.status === 'Ожидает'"
            variant="danger"
            size="sm"
            @click.stop="reject(row)"
          >
            Откл.
          </AppButton>
          <AppButton v-if="row.status !== 'Ожидает'" variant="ghost" size="sm" :icon-only="true">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1 7s2.5-4.5 6-4.5S13 7 13 7s-2.5 4.5-6 4.5S1 7 1 7z" stroke="currentColor" stroke-width="1.4"/><circle cx="7" cy="7" r="2" stroke="currentColor" stroke-width="1.4"/></svg>
          </AppButton>
        </div>
      </template>
    </AppTable>

    <!-- New withdrawal modal -->
    <AppModal v-model="showModal" title="Заявка на вывод" subtitle="Создать новую заявку">
      <AppInput v-model="newW.client" label="Клиент" placeholder="ФИО или ID" />
      <AppInput v-model="newW.amount" label="Сумма (₽)" placeholder="0.00" type="number" />
      <AppSelect v-model="newW.method" label="Метод вывода" :options="methodOptions" placeholder="Выберите метод" />
      <AppInput v-model="newW.details" label="Реквизиты" placeholder="Номер карты / счёта / кошелька" />
      <template #footer>
        <AppButton variant="ghost" @click="showModal = false">Отмена</AppButton>
        <AppButton variant="primary" @click="createWithdrawal">Создать</AppButton>
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
const search = ref('')
const filterStatus = ref('')
const filterMethod = ref('')

const kpis = [
  { label: 'Сегодня выведено', value: '₽ 128 400', trend: 8 },
  { label: 'Ожидают обработки', value: '7', trend: -3 },
  { label: 'Средняя сумма', value: '₽ 8 200', trend: 5 },
  { label: 'Отклонено сегодня', value: '2', trend: -50 },
]

const statusOptions = [
  { value: 'Ожидает', label: 'Ожидает' },
  { value: 'Выполнено', label: 'Выполнено' },
  { value: 'Отклонено', label: 'Отклонено' },
  { value: 'В обработке', label: 'В обработке' },
]

const methodOptions = [
  { value: 'Карта', label: 'Банковская карта' },
  { value: 'СБП', label: 'СБП' },
  { value: 'Криптовалюта', label: 'Криптовалюта' },
  { value: 'USDT', label: 'USDT (TRC-20)' },
]

const cols = [
  { key: 'id', label: 'ID', width: '72px' },
  { key: 'client', label: 'Клиент' },
  { key: 'amount', label: 'Сумма', width: '120px' },
  { key: 'method', label: 'Метод', width: '150px' },
  { key: 'status', label: 'Статус', width: '130px' },
  { key: 'date', label: 'Дата', width: '90px' },
  { key: 'actions', label: '', width: '140px' },
]

const withdrawals = ref([
  { id: '2041', client: 'Иван Петров', amount: '₽ 5 000', method: 'Карта', status: 'Выполнено', date: '29.06' },
  { id: '2042', client: 'Мария Белова', amount: '₽ 3 200', method: 'СБП', status: 'Отклонено', date: '29.06' },
  { id: '2043', client: 'Алексей Крылов', amount: '₽ 15 000', method: 'USDT', status: 'Ожидает', date: '29.06' },
  { id: '2044', client: 'Светлана Орлова', amount: '₽ 22 000', method: 'Карта', status: 'Ожидает', date: '29.06' },
  { id: '2045', client: 'Дмитрий Новиков', amount: '₽ 8 750', method: 'Криптовалюта', status: 'В обработке', date: '28.06' },
  { id: '2046', client: 'Надежда Власова', amount: '₽ 4 500', method: 'СБП', status: 'Выполнено', date: '28.06' },
  { id: '2047', client: 'Сергей Морозов', amount: '₽ 50 000', method: 'USDT', status: 'Ожидает', date: '28.06' },
])

const filtered = computed(() =>
  withdrawals.value.filter(w => {
    const matchSearch = !search.value || w.client.toLowerCase().includes(search.value.toLowerCase()) || w.id.includes(search.value)
    const matchStatus = !filterStatus.value || w.status === filterStatus.value
    const matchMethod = !filterMethod.value || w.method === filterMethod.value
    return matchSearch && matchStatus && matchMethod
  })
)

function resetFilters() { search.value = ''; filterStatus.value = ''; filterMethod.value = '' }

function statusVariant(s: string) {
  if (s === 'Выполнено') return 'green'
  if (s === 'В обработке') return 'blue'
  if (s === 'Отклонено') return 'red'
  return 'yellow'
}

function methodIcon(m: string) {
  if (m === 'Карта') return `<svg width="13" height="13" viewBox="0 0 13 13" fill="none"><rect x="1" y="3" width="11" height="7.5" rx="1.5" stroke="currentColor" stroke-width="1.2"/><path d="M1 5.5h11" stroke="currentColor" stroke-width="1.2"/></svg>`
  if (m === 'СБП') return `<svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M6.5 1.5v10M2 4l4.5-2.5L11 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
  return `<svg width="13" height="13" viewBox="0 0 13 13" fill="none"><circle cx="6.5" cy="6.5" r="5.5" stroke="currentColor" stroke-width="1.2"/><path d="M4 6.5h5M6.5 4v5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>`
}

function approve(row: any) { row.status = 'В обработке' }
function reject(row: any) { row.status = 'Отклонено' }

const newW = ref({ client: '', amount: '', method: '', details: '' })
function createWithdrawal() {
  if (newW.value.client && newW.value.amount) {
    withdrawals.value.unshift({
      id: String(2048 + withdrawals.value.length),
      client: newW.value.client,
      amount: `₽ ${newW.value.amount}`,
      method: newW.value.method || 'Карта',
      status: 'Ожидает',
      date: new Date().toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }).slice(0, 5),
    })
  }
  showModal.value = false
  newW.value = { client: '', amount: '', method: '', details: '' }
}
</script>

<style scoped>
.kpi-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  display: flex; flex-direction: column; gap: 6px;
}
.kpi-label { font-size: 12px; color: var(--text-muted); }
.kpi-val { font-size: 24px; font-weight: 800; letter-spacing: -0.6px; color: var(--text-primary); font-variant-numeric: tabular-nums; }

.filters-row { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
.filters-row > * { flex: 1; min-width: 150px; }
.filters-row > button { flex: 0; }

.method-cell { display: flex; align-items: center; gap: 6px; color: var(--text-secondary); }
.method-icon { color: var(--text-muted); display: flex; }

.row-actions { display: flex; gap: 4px; }
</style>
