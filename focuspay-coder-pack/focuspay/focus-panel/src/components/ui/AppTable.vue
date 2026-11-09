<template>
  <div class="table-wrap">
    <table class="table">
      <thead>
        <tr>
          <th v-for="col in columns" :key="col.key" :style="col.width ? { width: col.width } : {}">
            {{ col.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="loading">
          <td :colspan="columns.length" class="cell-state">
            <span class="tbl-spinner" />
          </td>
        </tr>
        <tr v-else-if="!rows.length">
          <td :colspan="columns.length" class="cell-state">{{ emptyText ?? 'Нет данных' }}</td>
        </tr>
        <template v-else>
          <tr v-for="(row, ri) in rows" :key="ri" @click="emit('rowClick', row)" :class="{ 'row-clickable': hasRowClick }">
            <td v-for="col in columns" :key="col.key">
              <slot :name="col.key" :row="row" :value="row[col.key]">
                <span class="cell-text">{{ row[col.key] ?? '—' }}</span>
              </slot>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
export interface TableColumn {
  key: string
  label: string
  width?: string
}

const props = defineProps<{
  columns: TableColumn[]
  rows: Record<string, any>[]
  loading?: boolean
  emptyText?: string
}>()

const emit = defineEmits<{ (e: 'rowClick', row: Record<string, any>): void }>()
const hasRowClick = true
</script>

<style scoped>
.table-wrap {
  width: 100%;
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
}

.table { width: 100%; border-collapse: collapse; font-size: 13px; }

thead tr { border-bottom: 1px solid var(--border); }

th {
  padding: 10px 16px;
  text-align: left;
  font-size: 10.5px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.7px;
  text-transform: uppercase;
  background: var(--bg-elevated);
  white-space: nowrap;
  user-select: none;
}

tbody tr {
  border-bottom: 1px solid var(--border);
  transition: background var(--transition);
}
tbody tr:last-child { border-bottom: none; }
tbody tr.row-clickable { cursor: pointer; }
tbody tr:hover { background: var(--bg-elevated); }

td { padding: 11px 16px; color: var(--text-primary); vertical-align: middle; }

.cell-text { color: var(--text-primary); }

.cell-state {
  text-align: center;
  padding: 52px 16px;
  color: var(--text-muted);
  font-size: 13px;
}

.tbl-spinner {
  display: inline-block;
  width: 18px; height: 18px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--text-secondary);
  border-radius: 50%;
  animation: tbl-spin 0.55s linear infinite;
}
@keyframes tbl-spin { to { transform: rotate(360deg); } }
</style>
