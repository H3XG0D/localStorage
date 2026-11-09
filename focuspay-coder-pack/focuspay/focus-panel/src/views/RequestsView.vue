<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Заявки</h1>
        <p class="page-subtitle">{{ filtered.length }} из {{ requests.length }} записей</p>
      </div>
      <div class="page-actions">
        <AppButton variant="ghost" size="sm" @click="showFilters = !showFilters">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1 3h12M3 7h8M5 11h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          Фильтры
        </AppButton>
        <AppButton variant="primary" size="sm" @click="$router.push('/create')">
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M6.5 1v11M1 6.5h11" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
          Новая
        </AppButton>
      </div>
    </div>

    <!-- Filters panel -->
    <Transition name="slide-down">
      <div v-if="showFilters" class="filters-panel card">
        <div class="filters-row">
          <AppInput v-model="search" placeholder="Поиск по клиенту, ID..." type="search">
            <template #prefix>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4" stroke="currentColor" stroke-width="1.4"/><path d="M10 10l3 3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
            </template>
          </AppInput>
          <AppSelect v-model="filterStatus" placeholder="Все статусы" :options="statusOptions" />
          <AppSelect v-model="filterService" placeholder="Все услуги" :options="serviceOptions" />
          <AppButton variant="ghost" size="sm" @click="resetFilters">Сбросить</AppButton>
        </div>
      </div>
    </Transition>

    <!-- Table -->
    <AppTable :columns="columns" :rows="filtered" empty-text="Заявки не найдены">
      <template #id="{ value }">
        <span class="font-mono text-muted">#{{ value }}</span>
      </template>
      <template #status="{ value }">
        <AppBadge :variant="statusVariant(value)">{{ value }}</AppBadge>
      </template>
      <template #amount="{ value }">
        <span class="font-mono">{{ value }}</span>
      </template>
      <template #actions="{ row }">
        <div class="row-actions">
          <AppButton variant="ghost" size="sm" :icon-only="true" title="Открыть">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1 7s2.5-4.5 6-4.5S13 7 13 7s-2.5 4.5-6 4.5S1 7 1 7z" stroke="currentColor" stroke-width="1.4"/><circle cx="7" cy="7" r="2" stroke="currentColor" stroke-width="1.4"/></svg>
          </AppButton>
          <AppButton variant="ghost" size="sm" :icon-only="true" title="Редактировать">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M9.5 2.5l2 2L4 12H2v-2l7.5-7.5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
          </AppButton>
        </div>
      </template>
    </AppTable>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppTable from '@/components/ui/AppTable.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'

const showFilters = ref(true)
const search = ref('')
const filterStatus = ref('')
const filterService = ref('')

const statusOptions = [
  { value: 'Выполнено', label: 'Выполнено' },
  { value: 'В работе', label: 'В работе' },
  { value: 'Ожидает', label: 'Ожидает' },
  { value: 'Отклонено', label: 'Отклонено' },
]

const serviceOptions = [
  { value: 'Вывод', label: 'Вывод' },
  { value: 'Пополнение', label: 'Пополнение' },
  { value: 'Перевод', label: 'Перевод' },
  { value: 'Консультация', label: 'Консультация' },
]

const columns = [
  { key: 'id', label: 'ID', width: '72px' },
  { key: 'client', label: 'Клиент' },
  { key: 'service', label: 'Услуга', width: '130px' },
  { key: 'amount', label: 'Сумма', width: '110px' },
  { key: 'status', label: 'Статус', width: '120px' },
  { key: 'date', label: 'Дата', width: '100px' },
  { key: 'actions', label: '', width: '80px' },
]

const requests = [
  { id: '1046', client: 'Дмитрий Новиков', service: 'Перевод', amount: '₽ 8 750', status: 'Выполнено', date: '29.06' },
  { id: '1045', client: 'Мария Белова', service: 'Вывод', amount: '₽ 3 200', status: 'Отклонено', date: '29.06' },
  { id: '1044', client: 'Олег Кузнецов', service: 'Консультация', amount: '—', status: 'Ожидает', date: '29.06' },
  { id: '1043', client: 'Анна Сидорова', service: 'Пополнение', amount: '₽ 12 000', status: 'В работе', date: '28.06' },
  { id: '1042', client: 'Иван Петров', service: 'Вывод', amount: '₽ 5 000', status: 'Выполнено', date: '28.06' },
  { id: '1041', client: 'Светлана Орлова', service: 'Перевод', amount: '₽ 22 000', status: 'Выполнено', date: '27.06' },
  { id: '1040', client: 'Владимир Соколов', service: 'Вывод', amount: '₽ 7 500', status: 'Ожидает', date: '27.06' },
  { id: '1039', client: 'Татьяна Козлова', service: 'Консультация', amount: '—', status: 'Выполнено', date: '26.06' },
  { id: '1038', client: 'Алексей Лебедев', service: 'Пополнение', amount: '₽ 50 000', status: 'В работе', date: '26.06' },
  { id: '1037', client: 'Наталья Попова', service: 'Вывод', amount: '₽ 1 800', status: 'Отклонено', date: '25.06' },
]

const filtered = computed(() => {
  return requests.filter(r => {
    const matchSearch = !search.value || r.client.toLowerCase().includes(search.value.toLowerCase()) || r.id.includes(search.value)
    const matchStatus = !filterStatus.value || r.status === filterStatus.value
    const matchService = !filterService.value || r.service === filterService.value
    return matchSearch && matchStatus && matchService
  })
})

function resetFilters() {
  search.value = ''
  filterStatus.value = ''
  filterService.value = ''
}

function statusVariant(s: string) {
  if (s === 'Выполнено') return 'green'
  if (s === 'В работе') return 'blue'
  if (s === 'Отклонено') return 'red'
  return 'default'
}
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }

.filters-panel { padding: 14px 16px; }
.filters-row { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
.filters-row > * { flex: 1; min-width: 160px; }
.filters-row > button { flex: 0 0 auto; }

.row-actions { display: flex; gap: 2px; }

.slide-down-enter-active, .slide-down-leave-active { transition: opacity 180ms ease, transform 180ms ease; }
.slide-down-enter-from, .slide-down-leave-to { opacity: 0; transform: translateY(-6px); }
</style>
