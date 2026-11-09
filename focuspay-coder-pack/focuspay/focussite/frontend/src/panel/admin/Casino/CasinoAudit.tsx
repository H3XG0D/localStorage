import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import {
  getCasinoSettingsAudit,
  type AdminCasinoSettingsAuditRow,
} from "@/panel/lib/adminApi";
import { PanelApiError } from "@/panel/lib/panelApi";
import { Button, Card, DiffRow, Field, Input, PageHeader, Select } from "@/panel/ui/primitives";
import {
  AUDIT_KEY_LABELS,
  AUDIT_RETENTION_NOTE,
  AUDIT_WINDOWS,
  auditKeyLabel,
  formatAuditValue,
  groupAuditBatches,
  type AuditWindowId,
} from "@/panel/admin/Casino/casinoAuditModel";

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof PanelApiError ? error.message : fallback;
}

function formatWhen(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "medium" });
}

export function CasinoAudit() {
  const [windowId, setWindowId] = useState<AuditWindowId>("7d");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [key, setKey] = useState("");
  const [author, setAuthor] = useState("");
  const [appliedAuthor, setAppliedAuthor] = useState("");
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [items, setItems] = useState<AdminCasinoSettingsAuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const query: {
        window?: "24h" | "7d" | "30d";
        date_from?: string;
        date_to?: string;
        key?: string;
        changed_by?: string;
        q?: string;
        limit: number;
      } = { limit: 500 };
      if (windowId !== "custom") query.window = windowId;
      else {
        if (dateFrom) query.date_from = dateFrom;
        if (dateTo) query.date_to = dateTo;
      }
      if (key) query.key = key;
      if (appliedAuthor.trim()) query.changed_by = appliedAuthor.trim();
      if (appliedSearch.trim()) query.q = appliedSearch.trim();
      const response = await getCasinoSettingsAudit(query);
      setItems(response.items);
      setTotal(response.total);
    } catch (loadError) {
      setItems([]);
      setTotal(0);
      setError(getErrorMessage(loadError, "Не удалось загрузить аудит"));
    } finally {
      setLoading(false);
    }
  }, [windowId, dateFrom, dateTo, key, appliedAuthor, appliedSearch]);

  useEffect(() => {
    void load();
  }, [load]);

  const batches = useMemo(() => groupAuditBatches(items), [items]);
  const selected = batches.find((batch) => batch.batch_id === selectedId) ?? null;
  const keyOptions = useMemo(() => {
    const seen = new Set(Object.keys(AUDIT_KEY_LABELS));
    for (const row of items) seen.add(row.key);
    return [...seen].sort((a, b) => auditKeyLabel(a).localeCompare(auditKeyLabel(b), "ru"));
  }, [items]);

  const applySearch = () => setAppliedSearch(search);
  const applyAuthor = () => setAppliedAuthor(author);

  return (
    <div className="w-full space-y-5">
      <PageHeader
        title="Казино — Аудит настроек"
        subtitle="Одно сохранение — одна строка. Клик открывает было → стало справа, список не перезагружается."
        actions={
          <Button type="button" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
            Обновить
          </Button>
        }
      />

      <p className="text-[12.5px] text-[var(--text-muted)]" data-audit-retention="">
        {AUDIT_RETENTION_NOTE}
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-wrap gap-1">
          {AUDIT_WINDOWS.map((item) => (
            <Button
              key={item.id}
              type="button"
              size="sm"
              variant={windowId === item.id ? "primary" : "secondary"}
              onClick={() => setWindowId(item.id)}
            >
              {item.label}
            </Button>
          ))}
        </div>
        {windowId === "custom" ? (
          <>
            <Field label="С">
              <Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
            </Field>
            <Field label="По">
              <Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
            </Field>
          </>
        ) : null}
        <Field label="Ключ">
          <Select value={key} onChange={(event) => setKey(event.target.value)}>
            <option value="">все</option>
            {keyOptions.map((item) => (
              <option key={item} value={item}>
                {auditKeyLabel(item)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Автор">
          <Input
            value={author}
            placeholder="123"
            onChange={(event) => setAuthor(event.target.value)}
            onBlur={applyAuthor}
            onKeyDown={(event) => {
              if (event.key === "Enter") applyAuthor();
            }}
          />
        </Field>
        <Field label="Поиск">
          <Input
            value={search}
            placeholder="причина, ключ, значение"
            onChange={(event) => setSearch(event.target.value)}
            onBlur={applySearch}
            onKeyDown={(event) => {
              if (event.key === "Enter") applySearch();
            }}
          />
        </Field>
      </div>

      <div className="flex w-full flex-col items-start gap-6 xl:flex-row">
        <div className="min-w-0 w-full flex-1 space-y-3">
          {loading ? (
            <Card className="py-12 text-center text-[13px] text-[var(--text-muted)]" aria-busy="true">
              Загрузка аудита…
            </Card>
          ) : error ? (
            <Card className="space-y-3">
              <div role="alert" className="text-[13px] text-[var(--red)]">
                {error}
              </div>
              <Button type="button" size="sm" onClick={() => void load()}>
                Повторить
              </Button>
            </Card>
          ) : batches.length === 0 ? (
            <Card className="py-12 text-center text-[13px] text-[var(--text-muted)]">Нет записей за выбранный фильтр</Card>
          ) : (
            <>
              <p className="text-[12px] text-[var(--text-muted)]">
                {batches.length} сохранений · {items.length} полей
                {total > items.length ? ` · в базе ещё ${total - items.length}, сузьте фильтр` : ""}
              </p>
              <div className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-surface)]">
                {batches.map((batch) => {
                  const active = batch.batch_id === selectedId;
                  return (
                    <button
                      key={batch.batch_id}
                      type="button"
                      data-audit-batch={batch.batch_id}
                      onClick={() => setSelectedId(batch.batch_id)}
                      className={`flex w-full flex-col gap-1 px-4 py-3 text-left text-[13px] hover:bg-[var(--bg-elevated)] ${
                        active ? "bg-[var(--bg-elevated)]" : ""
                      }`}
                    >
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="font-medium">{formatWhen(batch.changed_at)}</span>
                        <span className="font-mono text-[12px] text-[var(--text-muted)]">
                          {batch.items.length} {batch.items.length === 1 ? "поле" : "полей"}
                        </span>
                      </div>
                      <div className="text-[12.5px] text-[var(--text-secondary)]">
                        {batch.changed_by} · {batch.reason || "без причины"}
                      </div>
                      <div className="truncate text-[12px] text-[var(--text-muted)]">
                        {batch.items.map((row) => auditKeyLabel(row.key)).join(" · ")}
                      </div>
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {selected ? (
          <aside
            className="w-full shrink-0 space-y-3 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-surface)] p-4 xl:sticky xl:top-4 xl:w-[320px]"
            data-audit-diff=""
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="text-[14px] font-semibold">Было → стало</h2>
                <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
                  {formatWhen(selected.changed_at)} · {selected.changed_by}
                </p>
              </div>
              <Button type="button" size="sm" variant="ghost" onClick={() => setSelectedId(null)}>
                Закрыть
              </Button>
            </div>
            <p className="text-[12.5px] text-[var(--text-secondary)]">{selected.reason || "без причины"}</p>
            <div className="max-h-[70vh] space-y-3 overflow-y-auto">
              {selected.items.map((row) => (
                <div key={row.id} className="border-t border-[var(--border)] pt-3 first:border-t-0 first:pt-0">
                  <DiffRow
                    label={auditKeyLabel(row.key)}
                    before={formatAuditValue(row.old_value)}
                    after={formatAuditValue(row.new_value)}
                  />
                </div>
              ))}
            </div>
          </aside>
        ) : (
          <aside className="hidden w-[320px] shrink-0 rounded-[var(--radius-lg)] border border-dashed border-[var(--border)] p-4 text-[12.5px] text-[var(--text-muted)] xl:block">
            Нажмите сохранение слева — здесь откроется построчный дифф. Прокрутка списка не сбрасывается.
          </aside>
        )}
      </div>
    </div>
  );
}
