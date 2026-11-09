import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { getPricing, patchPricing, type Dict } from "@/panel/lib/adminApi";
import { Button, Card, Field, Input, PageHeader, Select } from "@/panel/ui/primitives";
import { TierGridEditor } from "@/panel/ui/TierGridEditor";
import {
  attachDerivedMax,
  collectTierErrors,
  parseBound,
  tierRowError,
} from "@/panel/ui/tierGridModel";

type FieldSpec = {
  key: string;
  label: string;
  kind?: "number" | "bool" | "text" | "select";
  hint?: string;
  options?: { value: string; label: string }[];
};

type BuySpreadTierRow = {
  min_wager_rub: string;
  max_wager_rub: string;
  pct: string;
};

type ApiBuySpreadTier = { min_amount_rub?: unknown; pct?: unknown };

function emptySpreadRow(min: string): BuySpreadTierRow {
  return { min_wager_rub: min, max_wager_rub: "", pct: "20" };
}

function buySpreadTiersFromApi(raw: unknown, fallbackPct: unknown): BuySpreadTierRow[] {
  const rows = Array.isArray(raw) ? (raw as ApiBuySpreadTier[]) : [];
  if (!rows.length) {
    const pct = Number(fallbackPct);
    return attachDerivedMax([emptySpreadRow("0")].map((row) => ({
      ...row,
      pct: Number.isFinite(pct) ? String(pct) : "20",
    })));
  }
  return attachDerivedMax(
    rows.map((row) => ({
      min_wager_rub: String(row.min_amount_rub ?? 0),
      max_wager_rub: "",
      pct: String(row.pct ?? ""),
    })),
  );
}

function parseBuySpreadTiersForSave(rows: BuySpreadTierRow[]) {
  return rows.map((row) => ({
    min_amount_rub: Number(row.min_wager_rub),
    pct: Number(row.pct),
  }));
}

function buySpreadTierErrors(rows: BuySpreadTierRow[]) {
  const errors = collectTierErrors(rows, "tier-buy-spread");
  rows.forEach((row, index) => {
    const pct = parseBound(row.pct);
    if (pct == null || Number.isNaN(pct) || pct < 0 || pct > 50) {
      errors.push({
        id: `tier-buy-spread-${index}-pct`,
        message: `Ступень ${index + 1}: процент от 0 до 50`,
      });
    }
  });
  return errors;
}

const FIELDS: FieldSpec[] = [
  { key: "buy_spread_manual_pct", label: "Спред покупка ручной, %" },
  { key: "sell_spread_pct", label: "Спред продажа, %" },
  {
    key: "sell_pricing_mode",
    label: "Режим продажи",
    kind: "select",
    options: [
      { value: "discount", label: "Скидка (клиент получает меньше рынка)" },
      { value: "markup", label: "Наценка (доплачиваем за крипту)" },
    ],
    hint: "По умолчанию доплачиваем за крипту. Уже созданные заявки не пересчитываются.",
  },
  {
    key: "sell_markup_pct",
    label: "Наценка продажа, %",
    hint: "Только в режиме наценки. Клиенту: «доплачиваем N% за вашу крипту».",
  },
  {
    key: "sell_snap_enabled",
    label: "Подгонка суммы SELL",
    kind: "bool",
    hint: "Двигает сумму выплаты под открытый реквизит внутри коридора спреда или наценки",
  },
  { key: "sell_snap_cap_rub", label: "Лимит подгонки, ₽" },
  { key: "sell_spread_min_pct", label: "Коридор продажи, мин, %" },
  { key: "sell_spread_max_pct", label: "Коридор продажи, макс, %" },
  {
    key: "sell_deposit_address_btc",
    label: "BTC-адрес приёма (SELL)",
    kind: "text",
    hint: "Клиент увидит его на заявке. Пусто — адрес выдаёт оператор в чате",
  },
  {
    key: "payin_requisite_min_buy_paid",
    label: "Пейин с карты: мин. покупок",
    hint: "Сколько оплаченных BUY нужно, чтобы платить на карту реквизитчика вместо PayFast",
  },
  { key: "card_fee_auto_pct", label: "Комиссия карты авто, %" },
  { key: "card_fee_manual_pct", label: "Комиссия карты ручной, %" },
  { key: "sell_profit_factor_pct", label: "Фактор прибыли продажа, %" },
  { key: "user_cashback_base_pct", label: "Базовый кэшбэк, %" },
  { key: "user_cashback_tier_step_pct", label: "Шаг уровня кэшбэка, %" },
  { key: "user_cashback_tier_every_n", label: "Уровень каждые N" },
  { key: "user_cashback_max_pct", label: "Макс. кэшбэк, %" },
  { key: "user_referral_pct", label: "Реферальный, %" },
  { key: "review_bonus_text_rub", label: "Бонус за отзыв (текст), ₽" },
  { key: "review_bonus_photo_rub", label: "Бонус за отзыв (фото), ₽" },
];

export function AdminPricing() {
  const [settings, setSettings] = useState<Dict>({});
  const [preview, setPreview] = useState<Dict>({});
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [buySpreadTiers, setBuySpreadTiers] = useState<BuySpreadTierRow[]>([emptySpreadRow("0")]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getPricing()
      .then((r) => {
        const s = (r.settings ?? {}) as Dict;
        setSettings(s);
        setPreview((r.preview ?? {}) as Dict);
        setUpdatedAt(r.updated_at != null ? String(r.updated_at) : null);
        const seed: Record<string, string> = {};
        for (const f of FIELDS) {
          if (f.kind === "bool") seed[f.key] = s[f.key] ? "1" : "0";
          else if (f.kind === "select") seed[f.key] = String(s[f.key] ?? f.options?.[0]?.value ?? "");
          else seed[f.key] = String(s[f.key] ?? "");
        }
        setForm(seed);
        setBuySpreadTiers(buySpreadTiersFromApi(s.buy_spread_auto_tiers, s.buy_spread_auto_pct));
      })
      .catch((e) => {
        const message = e instanceof PanelApiError ? e.message : "Не удалось загрузить настройки";
        setError(message);
        toast.error(message);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(), [load]);

  function setField(key: string, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function save() {
    const changed: Dict = {};
    for (const f of FIELDS) {
      const raw = form[f.key];
      if (raw == null) continue;
      if (f.kind === "text" || f.kind === "select") {
        const next = f.kind === "text" ? raw.trim() : raw;
        if (next !== String(settings[f.key] ?? "")) changed[f.key] = next;
        continue;
      }
      if (raw === "") continue;
      if (f.kind === "bool") {
        const next = raw === "1";
        if (next !== Boolean(settings[f.key])) changed[f.key] = next;
        continue;
      }
      const next = Number(raw);
      if (Number.isNaN(next)) continue;
      if (next !== Number(settings[f.key] ?? NaN)) changed[f.key] = next;
    }
    const nextTiers = parseBuySpreadTiersForSave(buySpreadTiers);
    const prevTiers = Array.isArray(settings.buy_spread_auto_tiers)
      ? (settings.buy_spread_auto_tiers as ApiBuySpreadTier[])
      : [];
    const tiersChanged =
      JSON.stringify(nextTiers) !==
      JSON.stringify(
        prevTiers.map((row) => ({
          min_amount_rub: Number(row.min_amount_rub),
          pct: Number(row.pct),
        })),
      );
    if (tiersChanged) {
      const tierErrors = buySpreadTierErrors(buySpreadTiers);
      if (tierErrors.length) {
        toast.error(tierErrors[0]?.message ?? "Проверьте сетку спреда покупки");
        return;
      }
      changed.buy_spread_auto_tiers = nextTiers;
    }
    if (Object.keys(changed).length === 0) {
      toast.info("Нет изменений");
      return;
    }
    setBusy(true);
    try {
      await patchPricing(changed);
      toast.success("Сохранено");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Ценообразование"
        subtitle={
          updatedAt
            ? `Обновлено: ${updatedAt}. Новые тарифы действуют только для новых заявок.`
            : "Спреды, комиссии и бонусы. Экономика созданных заявок зафиксирована."
        }
        actions={
          <Button variant="primary" disabled={busy} onClick={save}>
            Сохранить
          </Button>
        }
      />

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">Предпросмотр курсов</div>
        {error && <div className="mb-3 rounded-[var(--radius)] border border-[var(--red)]/30 bg-[var(--red-bg)] p-3 text-[12px] text-[var(--red)]">{error}</div>}
        <div className="grid grid-cols-3 gap-4 max-[520px]:grid-cols-1">
          <PreviewRow label="Покупка авто" value={previewValue(preview.buy_auto, loading)} />
          <PreviewRow label="Покупка ручная" value={previewValue(preview.buy_manual, loading)} />
          <PreviewRow label="Продажа" value={previewValue(preview.sell, loading)} />
        </div>
      </Card>

      <div className="mt-4">
        <TierGridEditor<BuySpreadTierRow>
          title="Спред покупка авто по сумме"
          description="Процент зависит от суммы, которую клиент вводит в ₽. Первая ступень с 0 ₽, последняя без потолка. Пример: 0–1000 = 25%, от 1000 = 23%."
          rows={buySpreadTiers}
          columns={[
            { key: "min_wager_rub", label: "От, ₽", min: 0, lockFirst: true },
            { key: "max_wager_rub", label: "До, ₽", min: 0, drivesNextMin: true, placeholder: "∞" },
            { key: "pct", label: "%", min: 0, max: 50, step: "0.01" },
          ]}
          disabled={busy || loading}
          emptyRow={(min) => ({ ...emptySpreadRow(min), pct: buySpreadTiers[buySpreadTiers.length - 1]?.pct || "20" })}
          onChange={setBuySpreadTiers}
          addLabel="Добавить ступень"
          idPrefix="tier-buy-spread"
          rowError={(_row, index, rows) => {
            const range = tierRowError(rows, index);
            if (range) return range;
            const pct = parseBound(rows[index]?.pct ?? "");
            if (pct == null || Number.isNaN(pct) || pct < 0 || pct > 50) return "Процент от 0 до 50";
            return null;
          }}
        />
      </div>

      <Card>
        <div className="mb-4 text-[13.5px] font-semibold">Настройки</div>
        <div className="grid grid-cols-3 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
          {FIELDS.map((f) => (
            <Field key={f.key} label={f.label} hint={f.hint}>
              {f.kind === "bool" ? (
                <Select value={form[f.key] ?? "0"} onChange={(e) => setField(f.key, e.target.value)}>
                  <option value="0">Выключена</option>
                  <option value="1">Включена</option>
                </Select>
              ) : f.kind === "select" ? (
                <Select value={form[f.key] ?? f.options?.[0]?.value ?? ""} onChange={(e) => setField(f.key, e.target.value)}>
                  {(f.options ?? []).map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  inputMode={f.kind === "text" ? "text" : "decimal"}
                  value={form[f.key] ?? ""}
                  onChange={(e) => setField(f.key, e.target.value)}
                  className="font-mono"
                />
              )}
            </Field>
          ))}
        </div>
      </Card>
    </>
  );
}

function previewValue(value: unknown, loading: boolean) {
  if (loading) return "Загрузка…";
  if (value == null || value === "") return "Нет данных";
  return String(value);
}

function PreviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3">
      <span className="text-[11px] text-[var(--text-muted)]">{label}</span>
      <span className="font-mono text-[15px] font-semibold tabular-nums">{value}</span>
    </div>
  );
}
