import { useEffect, useState } from "react";
import { getVpnSettings, putVpnSettings, type VpnBillingSettings, type VpnPlan } from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input } from "@/panel/ui/primitives";
import { moneyRub } from "@/panel/admin/analytics/format";
import { planPrices, pluralDays, type PlanPrice } from "@/panel/admin/vpn/format";

export function SettingsTab() {
  const [cfg, setCfg] = useState<VpnBillingSettings | null>(null);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    getVpnSettings()
      .then((r) => setCfg({ ...r.settings, device_addons: r.settings.device_addons ?? [] }))
      .catch((e: Error) => setMsg({ text: e.message, ok: false }));
  }, []);
  if (!cfg) return <p className="text-[var(--text-muted)]">{msg?.text || "Загрузка…"}</p>;

  const update = (next: VpnBillingSettings) => {
    setCfg(next);
    setDirty(true);
    setMsg(null);
  };
  const save = async () => {
    setSaving(true);
    try {
      const r = await putVpnSettings(cfg);
      setCfg({ ...r.settings, device_addons: r.settings.device_addons ?? [] });
      setDirty(false);
      setMsg({ text: "Сохранено — бот покажет новые условия сразу", ok: true });
    } catch (e) {
      setMsg({ text: (e as Error).message || "ошибка сохранения", ok: false });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <OfferCards
        title="Тарифы"
        hint="Скидка считается от самого дорогого дня. Порядок карточек = порядок кнопок в боте."
        addLabel="+ тариф"
        removeLabel="Удалить тариф"
        items={cfg.plans}
        onChange={(plans) => update({ ...cfg, plans })}
      />

      <OfferCards
        title="Дополнительное устройство"
        hint="Срок места не зависит от подписки: недельная подписка может идти вместе с месячным местом. Каждая покупка добавляет одно устройство. Пустой список прячет кнопку в боте."
        addLabel="+ срок"
        removeLabel="Удалить срок"
        items={cfg.device_addons}
        onChange={(device_addons) => update({ ...cfg, device_addons })}
      />

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="space-y-3">
          <div className="text-[13.5px] font-semibold">Доступ к покупке</div>
          <Field label="Завершённых обменов" hint="Хватает одного условия: столько обменов или столько приглашённых. 0 обменов — покупка открыта всем.">
            <Input
              type="number"
              min={0}
              value={cfg.purchase_min_exchanges}
              onChange={(e) => update({ ...cfg, purchase_min_exchanges: Number(e.target.value) })}
            />
          </Field>
          <Field label="Приглашённых" hint="Либо столько людей пришли по рефералке. 0 — этот путь выключен.">
            <Input
              type="number"
              min={0}
              value={cfg.purchase_min_invited ?? 30}
              onChange={(e) => update({ ...cfg, purchase_min_invited: Number(e.target.value) })}
            />
          </Field>
          <p className="text-[11px] text-[var(--text-muted)]">
            В боте: либо {cfg.purchase_min_exchanges} обменов, либо {cfg.purchase_min_invited ?? 30} приглашённых.
          </p>
          <Gate need={cfg.purchase_min_exchanges} />
        </Card>

        <Card className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[13.5px] font-semibold">Пробный период</span>
            <Badge tone={cfg.trial.enabled ? "green" : "default"}>{cfg.trial.enabled ? "включён" : "выключен"}</Badge>
          </div>
          <label className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={cfg.trial.enabled}
              onChange={(e) => update({ ...cfg, trial: { ...cfg.trial, enabled: e.target.checked } })}
            />
            Выдавать пробный период
          </label>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Дней">
              <Input
                type="number"
                min={1}
                max={30}
                value={cfg.trial.days}
                onChange={(e) => update({ ...cfg, trial: { ...cfg.trial, days: Number(e.target.value) } })}
              />
            </Field>
            <Field label="Обменов">
              <Input
                type="number"
                min={0}
                value={cfg.trial.min_exchanges}
                onChange={(e) => update({ ...cfg, trial: { ...cfg.trial, min_exchanges: Number(e.target.value) } })}
              />
            </Field>
          </div>
          <p className="text-[11px] text-[var(--text-muted)]">Один раз на Telegram-аккаунт. 0 обменов — доступен всем.</p>
        </Card>

        <Card className="space-y-3">
          <div className="text-[13.5px] font-semibold">Отзыв о VPN</div>
          <Field label="Текст, ₽" hint="На баланс FocusPay. Раз в 7 дней, платная подписка или пробный период.">
            <Input
              type="number"
              min={1}
              value={cfg.review_bonus_text_rub ?? 25}
              onChange={(e) => update({ ...cfg, review_bonus_text_rub: Number(e.target.value) })}
            />
          </Field>
          <Field label="Текст и скрин, ₽" hint="Скрин приложения. Тот же канал и та же очередь операторов, что у обмена.">
            <Input
              type="number"
              min={1}
              value={cfg.review_bonus_photo_rub ?? 50}
              onChange={(e) => update({ ...cfg, review_bonus_photo_rub: Number(e.target.value) })}
            />
          </Field>
        </Card>

        <Card className="space-y-3">
          <div className="text-[13.5px] font-semibold">Приложение</div>
          <Field label="Ссылка на скачивание" hint="Кнопка «Скачать приложение» в боте. Прямой файл APK. Пусто — ссылка из настроек бота.">
            <Input
              placeholder="https://focuspay.org/vpn.apk"
              value={cfg.app_url}
              onChange={(e) => update({ ...cfg, app_url: e.target.value })}
            />
          </Field>
        </Card>
      </div>

      <div className="flex items-center gap-3">
        <Button variant="primary" disabled={saving || !dirty} onClick={save}>
          {saving ? "Сохранение…" : "Сохранить"}
        </Button>
        {dirty && !msg ? <span className="text-[12px] text-[var(--yellow)]">Есть несохранённые изменения</span> : null}
        {msg ? <span className={`text-[12px] ${msg.ok ? "text-[var(--green)]" : "text-[var(--red)]"}`}>{msg.text}</span> : null}
      </div>
    </div>
  );
}

function OfferCards({
  title,
  hint,
  addLabel,
  removeLabel,
  items,
  onChange,
}: {
  title: string;
  hint: string;
  addLabel: string;
  removeLabel: string;
  items: VpnPlan[];
  onChange: (next: VpnPlan[]) => void;
}) {
  const prices = planPrices(items);
  const setItem = (i: number, patch: Partial<VpnPlan>) =>
    onChange(items.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  return (
    <Card>
      <div className="mb-1 flex items-center justify-between gap-3">
        <span className="text-[13.5px] font-semibold">{title}</span>
        <Button size="sm" onClick={() => onChange([...items, { code: "", title: "", days: 30, price_rub: "0" }])}>
          {addLabel}
        </Button>
      </div>
      <div className="mb-4 text-[11px] text-[var(--text-muted)]">{hint}</div>
      {items.length === 0 ? <p className="text-[13px] text-[var(--text-muted)]">Нет сроков — в боте докупить устройство нельзя.</p> : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((p, i) => (
          <OfferCard
            key={i}
            plan={p}
            price={prices[i]}
            removeLabel={removeLabel}
            onChange={(patch) => setItem(i, patch)}
            onRemove={() => onChange(items.filter((_, j) => j !== i))}
          />
        ))}
      </div>
    </Card>
  );
}

function OfferCard({
  plan,
  price,
  removeLabel,
  onChange,
  onRemove,
}: {
  plan: VpnPlan;
  price: PlanPrice;
  removeLabel: string;
  onChange: (patch: Partial<VpnPlan>) => void;
  onRemove: () => void;
}) {
  return (
    <div className="space-y-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[15px] font-semibold">{plan.title || "Без названия"}</div>
          <div className="text-[11px] text-[var(--text-muted)]">{pluralDays(plan.days || 0)}</div>
        </div>
        {price.discountPct > 0 ? <Badge tone="green">−{price.discountPct}%</Badge> : null}
      </div>
      <div className="font-mono text-2xl font-extrabold tabular-nums">{moneyRub(plan.price_rub)}</div>
      <div className="text-[12px] text-[var(--text-secondary)]">{moneyRub(price.perDay, true)} в день</div>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Код">
          <Input value={plan.code} onChange={(e) => onChange({ code: e.target.value })} />
        </Field>
        <Field label="Название">
          <Input value={plan.title} onChange={(e) => onChange({ title: e.target.value })} />
        </Field>
        <Field label="Дней">
          <Input type="number" min={1} max={365} value={plan.days} onChange={(e) => onChange({ days: Number(e.target.value) })} />
        </Field>
        <Field label="Цена, ₽">
          <Input inputMode="decimal" value={plan.price_rub} onChange={(e) => onChange({ price_rub: e.target.value })} />
        </Field>
      </div>
      <Button size="sm" variant="ghost" className="text-[var(--red)]" onClick={onRemove}>
        {removeLabel}
      </Button>
    </div>
  );
}

function Gate({ need }: { need: number }) {
  if (!need) return <p className="text-[11px] text-[var(--text-muted)]">Покупка открыта всем.</p>;
  const sample = Math.min(need, Math.round(need * 0.3));
  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
      <div className="mb-1.5 text-[11px] text-[var(--text-muted)]">Так пользователь видит прогресс в боте</div>
      <div className="font-mono text-[13px] tracking-wider">
        {"▰".repeat(Math.round((sample / need) * 10))}
        {"▱".repeat(10 - Math.round((sample / need) * 10))} {sample} из {need}
      </div>
    </div>
  );
}
