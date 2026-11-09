import { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
  sortKey?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyField: keyof T | ((row: T) => string | number);
  onRowClick?: (row: T) => void;
  emptyMessage?: string;
  selectable?: boolean;
  selectedKeys?: Set<string | number>;
  onToggleRow?: (key: string | number) => void;
  onToggleAll?: (keys: (string | number)[]) => void;
  sortKey?: string;
  sortDir?: 'asc' | 'desc';
  onSort?: (key: string) => void;
  maxHeight?: string;
}

export function DataTable<T>({
  columns,
  data,
  keyField,
  onRowClick,
  emptyMessage = 'Нет данных',
  selectable,
  selectedKeys,
  onToggleRow,
  onToggleAll,
  sortKey,
  sortDir,
  onSort,
  maxHeight,
}: DataTableProps<T>) {
  const getKey = (row: T, i: number) =>
    typeof keyField === 'function' ? keyField(row) : (row[keyField] as string | number) ?? i;

  const allKeys = data.map((row, i) => getKey(row, i));
  const allSelected = selectable && data.length > 0 && allKeys.every((k) => selectedKeys?.has(k));

  return (
    <div className="table-wrap" style={maxHeight ? { maxHeight, overflow: 'auto' } : undefined}>
      <table className="data-table">
        <thead>
          <tr>
            {selectable && (
              <th className="w-10">
                <input
                  type="checkbox"
                  checked={!!allSelected}
                  onChange={() => onToggleAll?.(allKeys)}
                />
              </th>
            )}
            {columns.map((col) => (
              <th key={col.key} className={col.className}>
                {col.sortKey && onSort ? (
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 hover:text-accent"
                    onClick={() => onSort(col.sortKey!)}
                  >
                    {col.header}
                    {sortKey === col.sortKey ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
                  </button>
                ) : (
                  col.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.length === 0 ? (
            <tr>
              <td colSpan={columns.length + (selectable ? 1 : 0)} className="text-center text-muted py-8">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((row, i) => {
              const key = getKey(row, i);
              const selected = selectedKeys?.has(key);
              return (
                <tr
                  key={key}
                  onClick={() => onRowClick?.(row)}
                  className={`${onRowClick ? 'cursor-pointer' : ''} ${selected ? 'bg-accent/10' : ''}`}
                >
                  {selectable && (
                    <td onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={!!selected}
                        onChange={() => onToggleRow?.(key)}
                      />
                    </td>
                  )}
                  {columns.map((col) => (
                    <td key={col.key} className={col.className}>
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
