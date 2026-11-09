import { useEffect, useRef, useState, type ReactNode } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { MoreHorizontal } from "lucide-react";
import { Card, Input, cx } from "@/panel/ui/primitives";
import {
  appendRangeRow,
  applyUpperBound,
  insertRangeRow,
  removeRangeRow,
  type TierRangeRow,
} from "@/panel/ui/tierGridModel";

export type TierColumn<Row> = {
  key: Extract<keyof Row, string>;
  label: string;
  min?: number;
  max?: number;
  step?: string;
  /** First row of this column stays locked (cashback/commission min starts at 0). */
  lockFirst?: boolean;
  /** Editing this field writes the next row's min_wager_rub. */
  drivesNextMin?: boolean;
  /** Open the side panel; cell itself is not a number input. */
  computed?: boolean;
  placeholder?: string;
};

export type TierCellContext<Row> = {
  row: Row;
  index: number;
  rows: Row[];
  column: TierColumn<Row>;
};

export type TierGridEditorProps<Row> = {
  title: string;
  description?: ReactNode;
  rows: Row[];
  columns: TierColumn<Row>[];
  disabled?: boolean;
  emptyRow: (min: string) => Row;
  onChange: (rows: Row[]) => void;
  addLabel: string;
  idPrefix: string;
  computed?: Array<{ label: string; key: string; render: (row: Row, index: number, rows: Row[]) => ReactNode }>;
  rowError?: (row: Row, index: number, rows: Row[]) => string | null;
  renderPanel?: (cell: TierCellContext<Row>) => ReactNode;
};

type SelectedCell = { row: number; key: string };

export function TierGridEditor<Row extends TierRangeRow>({
  title,
  description,
  rows,
  columns,
  disabled,
  emptyRow,
  onChange,
  addLabel,
  idPrefix,
  computed,
  rowError,
  renderPanel,
}: TierGridEditorProps<Row>) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [pendingFocus, setPendingFocus] = useState<number | null>(null);
  const [selected, setSelected] = useState<SelectedCell | null>(null);

  useEffect(() => {
    if (pendingFocus == null) return;
    const input = hostRef.current?.querySelector<HTMLInputElement>(
      `[data-tier-index="${pendingFocus}"] input:not([disabled])`,
    );
    input?.focus();
    input?.select();
    setPendingFocus(null);
  }, [pendingFocus, rows]);

  function patch(index: number, key: Extract<keyof Row, string>, value: string) {
    const column = columns.find((item) => item.key === key);
    if (column?.drivesNextMin) {
      onChange(applyUpperBound(rows, index, value) as Row[]);
      return;
    }
    const next = [...rows];
    next[index] = { ...rows[index], [key]: value } as Row;
    onChange(next);
  }

  function addRow() {
    const next = appendRangeRow(rows, emptyRow);
    onChange(next);
    setPendingFocus(next.length - 1);
    setSelected({ row: next.length - 1, key: "min_wager_rub" });
  }

  function insertBelow(index: number) {
    const next = insertRangeRow(rows, index, emptyRow);
    onChange(next);
    setPendingFocus(index + 1);
    setSelected({ row: index + 1, key: "min_wager_rub" });
  }

  function duplicate(index: number) {
    const source = rows[index];
    const next = insertRangeRow(rows, index, (min) => ({ ...source, min_wager_rub: min, max_wager_rub: "" }));
    onChange(next);
    setPendingFocus(index + 1);
    setSelected({ row: index + 1, key: "min_wager_rub" });
  }

  const selectedColumn: TierColumn<Row> | null = (() => {
    if (selected == null) return null;
    const fromColumns = columns.find((column) => column.key === selected.key);
    if (fromColumns) return fromColumns;
    const fromComputed = computed?.find((column) => column.key === selected.key);
    if (!fromComputed) return null;
    return { key: selected.key as Extract<keyof Row, string>, label: fromComputed.label, computed: true };
  })();
  const selectedRow = selected != null ? rows[selected.row] : undefined;

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[14px] font-semibold">{title}</h2>
        {description ? <p className="mt-1 text-[12px] text-[var(--text-muted)]">{description}</p> : null}
      </div>
      <div className="flex flex-col gap-4">
        <div ref={hostRef} className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[880px] border-collapse text-left text-[12.5px]">
            <thead>
              <tr className="border-b border-[var(--border)] text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                {columns.map((column) => (
                  <th key={column.key} className="whitespace-nowrap px-2 py-2 font-semibold">
                    {column.label}
                  </th>
                ))}
                {computed?.map((column) => (
                  <th key={column.key} className="whitespace-nowrap px-2 py-2 font-semibold">
                    {column.label}
                  </th>
                ))}
                <th className="w-10 px-1 py-2">
                  <span className="sr-only">Действия</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const error = rowError?.(row, index, rows) ?? null;
                return (
                  <tr
                    key={index}
                    data-tier-row=""
                    data-tier-index={index}
                    className={cx(
                      "border-b border-[var(--border)] last:border-0",
                      error && "bg-[var(--red-bg)]/40",
                    )}
                  >
                    {columns.map((column) => {
                      const inputId = `${idPrefix}-${index}-${column.key}`;
                      return (
                        <td key={column.key} className="whitespace-nowrap px-2 py-1.5 align-middle">
                          <Input
                            id={inputId}
                            type="number"
                            min={column.min ?? 0}
                            max={column.max}
                            step={column.step}
                            placeholder={column.placeholder}
                            value={String(row[column.key] ?? "")}
                            disabled={disabled || (column.lockFirst && index === 0)}
                            aria-invalid={Boolean(error)}
                            className="h-8 px-2"
                            onFocus={() => setSelected({ row: index, key: column.key })}
                            onChange={(event) => patch(index, column.key, event.target.value)}
                          />
                        </td>
                      );
                    })}
                    {computed?.map((column) => (
                      <td key={column.key} className="whitespace-nowrap px-2 py-1.5 align-middle">
                        <button
                          type="button"
                          data-tier-cost=""
                          className={cx(
                            "w-full rounded-[var(--radius)] px-2 py-1.5 text-left text-[12.5px] text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]",
                            selected?.row === index && selected.key === column.key && "bg-[var(--bg-elevated)] text-[var(--text-primary)]",
                          )}
                          onClick={() => setSelected({ row: index, key: column.key })}
                        >
                          {column.render(row, index, rows)}
                        </button>
                      </td>
                    ))}
                    <td className="px-1 py-1.5 align-middle">
                      <RowMenu
                        disabled={disabled}
                        canDelete={index > 0 && rows.length > 1}
                        onInsert={() => insertBelow(index)}
                        onDuplicate={() => duplicate(index)}
                        onDelete={() => onChange(removeRangeRow(rows, index))}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.map((row, index) => {
            const error = rowError?.(row, index, rows) ?? null;
            if (!error) return null;
            return (
              <p key={`err-${index}`} className="mt-1 text-[12px] text-[var(--red)]">
                Ступень {index + 1}: {error}
              </p>
            );
          })}
          <button
            type="button"
            disabled={disabled}
            onClick={addRow}
            className="mt-3 text-[13px] text-[var(--text-secondary)] underline-offset-2 hover:text-[var(--text-primary)] hover:underline disabled:opacity-50"
          >
            {addLabel}
          </button>
        </div>
        {selected && selectedRow && selectedColumn && renderPanel ? (
          <aside className="w-full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
              {selectedColumn.label} · ступень {selected.row + 1}
            </p>
            <div className="mt-2 text-[12.5px] leading-relaxed text-[var(--text-secondary)]">
              {renderPanel({ row: selectedRow, index: selected.row, rows, column: selectedColumn })}
            </div>
          </aside>
        ) : null}
      </div>
    </Card>
  );
}

function RowMenu({
  disabled,
  canDelete,
  onInsert,
  onDuplicate,
  onDelete,
}: {
  disabled?: boolean;
  canDelete: boolean;
  onInsert: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          data-tier-row-menu=""
          disabled={disabled}
          aria-label="Действия строки"
          className="flex h-8 w-8 items-center justify-center rounded-[var(--radius)] text-[var(--text-muted)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] disabled:opacity-50"
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={4}
          className="z-50 min-w-[180px] rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-surface)] p-1 shadow-[var(--shadow-lg)]"
        >
          <MenuItem onSelect={onInsert}>Вставить ниже</MenuItem>
          <MenuItem onSelect={onDuplicate}>Дублировать</MenuItem>
          <MenuItem disabled={!canDelete} onSelect={onDelete}>
            Удалить
          </MenuItem>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function MenuItem({
  children,
  disabled,
  onSelect,
}: {
  children: ReactNode;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <DropdownMenu.Item
      disabled={disabled}
      onSelect={onSelect}
      className="cursor-pointer rounded-[var(--radius-sm)] px-2.5 py-1.5 text-[12.5px] text-[var(--text-primary)] outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-40 data-[highlighted]:bg-[var(--bg-elevated)]"
    >
      {children}
    </DropdownMenu.Item>
  );
}
