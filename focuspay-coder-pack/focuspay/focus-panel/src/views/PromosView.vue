<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Промокоды</h1>
        <p class="page-subtitle">{{ promos.length }} промокодов · {{ activeCount }} активных</p>
      </div>
      <AppButton variant="primary" size="sm" @click="showModal = true">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M6.5 1v11M1 6.5h11" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        Создать промокод
      </AppButton>
    </div>

    <!-- Stats -->
    <div class="grid-4">
      <div class="promo-stat" v-for="s in stats" :key="s.label">
        <div class="promo-stat-val">{{ s.value }}</div>
        <div class="promo-stat-label">{{ s.label }}</div>
      </div>
    </div>

    <!-- Filters -->
    <div class="filters-row">
      <AppInput v-model="search" placeholder="Поиск по коду..." type="search">
        <template #prefix>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4" stroke="currentColor" stroke-width="1.4"/><path d="M10 10l3 3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
        </template>
      </AppInput>
      <AppSelect v-model="filterStatus" :options="statusOptions" placeholder="Все статусы" />
    </div>

    <!-- Table -->
    <AppTable :columns="cols" :rows="filtered">
      <template #code="{ value }">
        <div class="code-cell">
          <code class="promo-code">{{ value }}</code>
          <button class="copy-btn" @click.stop="copy(value)" title="Копировать">
            <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><rect x="4" y="4" width="8" height="8" rx="1.5" stroke="currentColor" stroke-width="1.3"/><path d="M9 4V2.5A1.5 1.5 0 007.5 1H2.5A1.5 1.5 0 001 2.5v5A1.5 1.5 0 002.5 9H4" stroke="currentColor" stroke-width="1.3"/></svg>
          </button>
        </div>
      </template>
      <template #discount="{ value }">
        <span class="font-mono">{{ value }}</span>
      </template>
      <template #status="{ value }">
        <AppBadge :variant="value === 'Активен' ? 'green' : value === 'Ограничен' ? 'yellow' : 'default'">{{ value }}</AppBadge>
      </template>
      <template #used="{ row }">
        <div class="usage-cell">
          <span class="font-mono">{{ row.used }} / {{ row.limit }}</span>
          <div class="usage-bar">
            <div class="usage-fill" :style="{ width: Math.min(100, row.used / row.limit * 100) + '%' }" />
          </div>
        </div>
      </template>
      <template #actions="{ row }">
        <div class="row-actions">
          <AppButton variant="ghost" size="sm" :icon-only="true" @click.stop="togglePromo(row)" :title="row.status === 'Активен' ? 'Деактивировать' : 'Активировать'">
            <svg v-if="row.status === 'Активен'" width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="2" y="3" width="4" height="8" rx="1" fill="currentColor"/><rect x="8" y="3" width="4" height="8" rx="1" fill="currentColor"/></svg>
            <svg v-else width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 2l9 5-9 5V2z" fill="currentColor"/></svg>
          </AppButton>
          <AppButton variant="danger" size="sm" :icon-only="true" @click.stop title="Удалить">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 4h10M5 4V2.5h4V4M5.5 6.5v4M8.5 6.5v4M3 4l1 7.5h6L11 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </AppButton>
        </div>
      </template>
    </AppTable>

    <!-- Create modal -->
    <AppModal v-model="showModal" title="Новый промокод" subtitle="Создайте промокод для клиентов">
      <AppInput v-model="newPromo.code" label="Код" placeholder="SUMMER2026">
        <template #suffix>
          <button class="gen-btn" @click="generateCode" title="Сгенерировать">
            <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M11 6.5A4.5 4.5 0 112 6.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M11 3v3.5H7.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        </template>
      </AppInput>
      <div class="grid-2">
        <AppSelect v-model="newPromo.type" label="Тип скидки" :options="discountTypes" placeholder="Тип" />
        <AppInput v-model="newPromo.value" label="Размер скидки" placeholder="10" type="number" />
      </div>
      <div class="grid-2">
        <AppInput v-model="newPromo.limit" label="Лимит использований" placeholder="100" type="number" />
        <AppInput v-model="newPromo.expires" label="Дата окончания" type="date" />
      </div>
      <template #footer>
        <AppButton variant="ghost" @click="showModal = false">Отмена</AppButton>
        <AppButton variant="primary" @click="createPromo">Создать</AppButton>
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

const promos = ref([
  { code: 'SUMMER2026', discount: '15%', type: 'percent', used: 42, limit: 100, status: 'Активен', expires: '31.07.26' },
  { code: 'WELCOME10', discount: '10%', type: 'percent', used: 100, limit: 100, status: 'Исчерпан', expires: '01.01.27' },
  { code: 'VIP500', discount: '₽ 500', type: 'fixed', used: 8, limit: 50, status: 'Активен', expires: '31.12.26' },
  { code: 'BONUS20', discount: '20%', type: 'percent', used: 78, limit: 80, status: 'Ограничен', expires: '15.07.26' },
  { code: 'NEW2026', discount: '₽ 200', type: 'fixed', used: 0, limit: 200, status: 'Активен', expires: '01.01.27' },
])

const activeCount = computed(() => promos.value.filter(p => p.status === 'Активен').length)

const stats = [
  { label: 'Всего промокодов', value: computed(() => promos.value.length) },
  { label: 'Активных', value: activeCount },
  { label: 'Использований сегодня', value: 23 },
  { label: 'Скидок выдано (₽)', value: '14 200' },
]

const cols = [
  { key: 'code', label: 'Промокод' },
  { key: 'discount', label: 'Скидка', width: '100px' },
  { key: 'used', label: 'Использования' },
  { key: 'status', label: 'Статус', width: '120px' },
  { key: 'expires', label: 'До', width: '90px' },
  { key: 'actions', label: '', width: '90px' },
]

const statusOptions = [
  { value: 'Активен', label: 'Активен' },
  { value: 'Исчерпан', label: 'Исчерпан' },
  { value: 'Ограничен', label: 'Ограничен' },
]

const discountTypes = [
  { value: 'percent', label: 'Процент (%)' },
  { value: 'fixed', label: 'Фиксированная (₽)' },
]

const newPromo = ref({ code: '', type: '', value: '', limit: '', expires: '' })

const filtered = computed(() => {
  return promos.value.filter(p => {
    const matchSearch = !search.value || p.code.toLowerCase().includes(search.value.toLowerCase())
    const matchStatus = !filterStatus.value || p.status === filterStatus.value
    return matchSearch && matchStatus
  })
})

function copy(code: string) {
  navigator.clipboard.writeText(code)
}

function generateCode() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
  newPromo.value.code = Array.from({ length: 8 }, () => chars[Math.floor(Math.random() * chars.length)]).join('')
}

function togglePromo(row: any) {
  row.status = row.status === 'Активен' ? 'Исчерпан' : 'Активен'
}

function createPromo() {
  showModal.value = false
  newPromo.value = { code: '', type: '', value: '', limit: '', expires: '' }
}
</script>

<style scoped>
.promo-stat {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
}
.promo-stat-val { font-size: 26px; font-weight: 800; letter-spacing: -0.8px; color: var(--text-primary); }
.promo-stat-label { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

.filters-row { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
.filters-row > * { flex: 1; min-width: 160px; max-width: 280px; }

.code-cell { display: flex; align-items: center; gap: 8px; }
.promo-code {
  font-family: var(--font-mono);
  font-size: 12.5px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 2px 8px;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}
.copy-btn {
  color: var(--text-muted); display: flex; cursor: pointer;
  padding: 3px; border-radius: 4px;
  transition: color var(--transition), background var(--transition);
}
.copy-btn:hover { color: var(--text-primary); background: var(--bg-elevated); }

.usage-cell { display: flex; flex-direction: column; gap: 4px; }
.usage-bar { height: 3px; background: var(--bg-elevated); border-radius: 2px; width: 80px; }
.usage-fill { height: 100%; background: var(--text-muted); border-radius: 2px; transition: width 0.4s ease; }

.row-actions { display: flex; gap: 4px; }

.gen-btn {
  color: var(--text-muted); display: flex; cursor: pointer;
  transition: color var(--transition);
}
.gen-btn:hover { color: var(--text-primary); }
</style>
