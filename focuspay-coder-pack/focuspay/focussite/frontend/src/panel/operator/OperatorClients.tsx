import { useState } from "react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { banUser, getUser, searchUsers, unbanUser } from "@/panel/lib/operatorApi";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Table, cx, type Column } from "@/panel/ui/primitives";

type UserRow = Record<string, unknown> & { user_id?: number; id?: number; username?: string; first_name?: string };

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}

export function OperatorClients() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [profile, setProfile] = useState<UserRow | null>(null);

  async function doSearch() {
    if (q.trim().length < 1) return;
    setLoading(true);
    try {
      const r = await searchUsers(q.trim(), 30);
      setRows((r.users as UserRow[]) || []);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setLoading(false);
    }
  }

  async function openProfile(row: UserRow) {
    const id = row.user_id ?? row.id;
    if (id == null) return;
    try {
      setProfile(await getUser(id));
    } catch {
      setProfile(row);
    }
  }

  const cols: Column<UserRow>[] = [
    { key: "id", label: "ID", width: "90px", render: (r) => <span className="font-mono">{r.user_id ?? r.id ?? "—"}</span> },
    { key: "name", label: "Клиент", render: (r) => r.first_name || r.username || "—" },
    { key: "username", label: "Username", render: (r) => (r.username ? `@${r.username}` : "—") },
    { key: "total_orders", label: "Заявок", width: "90px", align: "right", render: (r) => String(r.total_orders ?? "—") },
  ];

  return (
    <>
      <PageHeader title="Клиенты" subtitle="Поиск и профиль клиента" />
      <Card>
        <div className="flex gap-2">
          <Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doSearch()} placeholder="Telegram ID или @username" />
          <Button variant="primary" onClick={doSearch} disabled={loading}>
            Найти
          </Button>
        </div>
      </Card>
      <Card>
        <Table columns={cols} rows={rows} empty={loading ? "Поиск…" : "Введите запрос и нажмите «Найти»"} onRowClick={openProfile} />
      </Card>

      {profile && <ClientModal user={profile} onClose={() => setProfile(null)} onChanged={() => setProfile(null)} />}
    </>
  );
}

function ClientModal({ user, onClose, onChanged }: { user: UserRow; onClose: () => void; onChanged: () => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const id = (user.user_id ?? user.id) as number;
  const banned = !!user.is_banned;

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      onChanged();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open title={user.first_name || user.username || `Клиент ${id}`} onClose={onClose}>
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-2 text-[13px]">
          {[
            ["ID", String(id)],
            ["Username", user.username ? `@${user.username}` : "—"],
            ["Заявок", String(user.total_orders ?? "—")],
            ["Оплачено", String(user.paid_orders ?? "—")],
            ["Оборот ₽", money(user.total_fiat)],
            ["Кэшбэк ₽", money(user.cashback_rub)],
          ].map(([l, v]) => (
            <div key={l} className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5">
              <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{l}</div>
              <div className={cx("mt-0.5 text-[13px]", l.includes("₽") && "font-mono")}>{v}</div>
            </div>
          ))}
        </div>

        <div className="border-t border-[var(--border)] pt-4">
          {banned ? (
            <Button variant="secondary" disabled={busy} onClick={() => run(() => unbanUser(id), "Разбанен")}>
              Разбанить клиента
            </Button>
          ) : (
            <div className="flex flex-col gap-2">
              <Field label="Причина блокировки">
                <Input value={reason} onChange={(e) => setReason(e.target.value)} />
              </Field>
              <div className="flex gap-2">
                <Button variant="danger" disabled={busy} onClick={() => run(() => banUser(id, reason, "hard"), "Заблокирован (hard)")}>
                  Бан (hard)
                </Button>
                <Button variant="secondary" disabled={busy} onClick={() => run(() => banUser(id, reason, "soft"), "Заблокирован (soft)")}>
                  Бан (soft)
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
