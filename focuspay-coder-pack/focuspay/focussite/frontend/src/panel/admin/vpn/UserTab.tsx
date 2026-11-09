import { useCallback, useEffect, useState } from "react";
import { getVpnUser, resolveVpnUser, revokeVpnDevice, setVpnTrusted, type Dict, type VpnDevice, type VpnUser } from "@/panel/lib/adminApi";
import { Badge, Button, Card, Input, Kpi, Modal, Table, type Column } from "@/panel/ui/primitives";
import { moneyRub, num } from "@/panel/admin/analytics/format";
import { PURCHASE_STATUS, pluralDays, purchaseTitle, when } from "@/panel/admin/vpn/format";

const PLATFORM: Record<string, string> = { android: "Android", ios: "iOS", windows: "Windows", macos: "macOS", linux: "Linux" };

export function UserTab({ telegramId, onChange }: { telegramId: string; onChange: (telegramId: string) => void }) {
  const [query, setQuery] = useState(telegramId);
  const [user, setUser] = useState<VpnUser | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [unbind, setUnbind] = useState<VpnDevice | null>(null);
  const [busy, setBusy] = useState(false);
  const [trustBusy, setTrustBusy] = useState(false);

  const load = useCallback(() => {
    if (!telegramId) return;
    setLoading(true);
    setError("");
    getVpnUser(telegramId)
      .then(setUser)
      .catch((e: Error) => { setUser(null); setError(e.message || "не удалось загрузить"); })
      .finally(() => setLoading(false));
  }, [telegramId]);
  useEffect(load, [load]);
  useEffect(() => setQuery(telegramId), [telegramId]);

  const revoke = async () => {
    if (!unbind) return;
    setBusy(true);
    try {
      await revokeVpnDevice(telegramId, unbind.id);
      setUnbind(null);
      load();
    } catch (e) {
      setError((e as Error).message || "не удалось отвязать");
      setUnbind(null);
    } finally {
      setBusy(false);
    }
  };

  const find = async () => {
    const raw = query.trim();
    if (!raw) return;
    const body = raw.replace(/^@/, "");
    if (/^\d+$/.test(body)) {
      onChange(body);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const found = await resolveVpnUser(raw);
      onChange(String(found.telegram_id));
    } catch (e) {
      setUser(null);
      setError((e as Error).message || "пользователь не найден");
    } finally {
      setLoading(false);
    }
  };

  const toggleTrusted = async (trusted: boolean) => {
    setTrustBusy(true);
    setError("");
    try {
      await setVpnTrusted(telegramId, trusted);
      load();
    } catch (e) {
      setError((e as Error).message || "не удалось изменить доступ");
    } finally {
      setTrustBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <Card>
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => { e.preventDefault(); void find(); }}
        >
          <Input
            className="w-72"
            placeholder="Telegram ID или @username"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Button type="submit" variant="primary" disabled={!query.trim() || loading}>
            {loading ? "Загрузка…" : "Найти"}
          </Button>
        </form>
      </Card>

      {error ? <Card className="text-[var(--red)]">{error}</Card> : null}
      {!telegramId ? (
        <p className="text-[13px] text-[var(--text-muted)]">
          Введите Telegram ID или @username — или нажмите на ID во вкладках «Покупки» и «Сверка».
        </p>
      ) : null}
      {user ? <UserCard user={user} trustBusy={trustBusy} onTrusted={toggleTrusted} onUnbind={setUnbind} /> : null}

      <Modal
        open={Boolean(unbind)}
        title="Отвязать устройство?"
        onClose={() => setUnbind(null)}
        footer={
          <>
            <Button onClick={() => setUnbind(null)}>Отмена</Button>
            <Button variant="danger" disabled={busy} onClick={revoke}>{busy ? "Отвязываем…" : "Отвязать"}</Button>
          </>
        }
      >
        <p className="text-[13px] text-[var(--text-secondary)]">
          VPN на «{unbind?.name}» отключится сразу. Пользователь сможет войти с другого устройства. Подписка не меняется.
        </p>
      </Modal>
    </div>
  );
}

function UserCard({
  user,
  trustBusy,
  onTrusted,
  onUnbind,
}: {
  user: VpnUser;
  trustBusy: boolean;
  onTrusted: (trusted: boolean) => void;
  onUnbind: (d: VpnDevice) => void;
}) {
  const sub = user.subscription;
  const { have, need } = user.exchanges;
  const pct = need > 0 ? Math.min(100, Math.round((have / need) * 100)) : 100;

  const purchaseColumns: Column<Dict>[] = [
    { key: "created_at", label: "Создано", render: (r) => when(r.created_at) },
    { key: "plan_code", label: "Тариф", render: (r) => (r.kind === "trial" ? <Badge tone="purple">триал</Badge> : purchaseTitle(r)) },
    { key: "days", label: "Дней", align: "right", render: (r) => num(r.days) },
    { key: "price_rub", label: "Сумма", align: "right", render: (r) => moneyRub(r.price_rub, true) },
    {
      key: "status",
      label: "Статус",
      render: (r) => {
        const s = PURCHASE_STATUS[String(r.status)] || { label: String(r.status), tone: "default" as const };
        return <Badge tone={s.tone}>{s.label}</Badge>;
      },
    },
  ];

  return (
    <>
      {user.cp_error ? (
        <Card className="border-[var(--yellow)]/40 text-[var(--yellow)]">Control plane недоступен: {user.cp_error}</Card>
      ) : null}
      {(user.username || user.first_name) ? (
        <p className="text-[13px] text-[var(--text-secondary)]">
          {user.username ? `@${String(user.username).replace(/^@/, "")}` : "без юзернейма"}
          {user.first_name ? ` · ${user.first_name}` : ""}
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          label="Подписка"
          value={sub.active ? <span className="text-[var(--green)]">активна</span> : <span className="text-[var(--text-muted)]">нет</span>}
          hint={sub.active ? `${sub.status === "trialing" ? "триал" : sub.plan || "—"} · до ${when(sub.ends_at)} · ${pluralDays(sub.days_left)}` : "дней не осталось"}
        />
        <Kpi label="Баланс FocusPay" value={moneyRub(user.available_rub, true)} />
        <Kpi
          label="Обмены"
          value={`${have} / ${need}`}
          hint={
            <div className="space-y-1">
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--bg-overlay)]">
                <div className="h-full rounded-full" style={{ width: `${pct}%`, background: user.purchase_open ? "var(--green)" : "var(--blue)" }} />
              </div>
              <span>
                {user.trusted
                  ? "покупка открыта · доверенный аккаунт"
                  : user.purchase_open
                    ? "покупка открыта"
                    : `до покупки ещё ${Math.max(0, need - have)}`}
              </span>
            </div>
          }
        />
        <Kpi
          label="Пробный период"
          value={user.trial.used ? "использован" : user.trial_available ? "доступен" : "недоступен"}
          hint={user.trial.enabled ? pluralDays(user.trial.days) : "выключен в настройках"}
        />
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-[13.5px] font-semibold">Доверенный аккаунт</span>
              {user.trusted ? <Badge tone="green">Доверенный</Badge> : null}
            </div>
            <p className="text-[12px] text-[var(--text-muted)]">
              Покупка тарифов и дополнительного устройства без 10 обменов и 30 приглашённых. Оплата с баланса как обычно.
            </p>
          </div>
          <Button variant={user.trusted ? "danger" : "primary"} disabled={trustBusy} onClick={() => onTrusted(!user.trusted)}>
            {trustBusy ? "Сохраняем…" : user.trusted ? "Вернуть ограничение" : "Снять ограничение"}
          </Button>
        </div>
      </Card>

      <Card>
        <div className="mb-3 flex items-center justify-between gap-2">
          <span className="text-[13.5px] font-semibold">Устройства</span>
          <Badge>{user.devices.length}</Badge>
        </div>
        {user.devices.length === 0 ? (
          <p className="text-[13px] text-[var(--text-muted)]">Устройств нет — пользователь ещё не входил в приложение.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {user.devices.map((d) => (
              <div key={d.id} className="flex items-start justify-between gap-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3.5">
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-semibold">{d.name || "Устройство"}</div>
                  <div className="text-[11px] text-[var(--text-muted)]">
                    {PLATFORM[d.platform] || d.platform} · с {when(d.created_at)}
                  </div>
                  <div className="mt-1.5">
                    <Badge tone={d.connected ? "green" : "default"}>{d.connected ? "подключено" : "не в сети"}</Badge>
                  </div>
                </div>
                <Button size="sm" variant="danger" onClick={() => onUnbind(d)}>Отвязать</Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">Покупки</div>
        <Table columns={purchaseColumns} rows={user.purchases} empty="Покупок и триалов не было" />
      </Card>
    </>
  );
}
