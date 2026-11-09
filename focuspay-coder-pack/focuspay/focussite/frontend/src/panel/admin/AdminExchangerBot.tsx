import { useCallback, useEffect, useState } from "react";
import { Bot, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  cancelExchangerBotBroadcast,
  createExchangerBotBroadcast,
  createExchangerBotMember,
  deleteExchangerBotMember,
  deleteExchangerBotToken,
  getExchangerBot,
  getExchangerBotMembers,
  getExternalExchangers,
  listExchangerBotBroadcasts,
  patchExchangerBotMember,
  previewExchangerBotBroadcast,
  putExchangerBotToken,
  reconfigureExchangerBot,
  type Dict,
} from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, PageHeader, Table, type Column } from "@/panel/ui/primitives";

function asRows(r: unknown, ...keys: string[]): Dict[] {
  if (Array.isArray(r)) return r as Dict[];
  if (r && typeof r === "object") {
    const rec = r as Dict;
    for (const key of keys) {
      const val = rec[key];
      if (Array.isArray(val)) return val as Dict[];
    }
  }
  return [];
}

export function AdminExchangerBot() {
  const [bot, setBot] = useState<Dict | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [members, setMembers] = useState<Dict[]>([]);
  const [shops, setShops] = useState<Dict[]>([]);
  const [jobs, setJobs] = useState<Dict[]>([]);
  const [tgId, setTgId] = useState("");
  const [shopId, setShopId] = useState("");
  const [role, setRole] = useState("owner");
  const [label, setLabel] = useState("");
  const [audience, setAudience] = useState("all");
  const [broadcastText, setBroadcastText] = useState("");
  const [previewCount, setPreviewCount] = useState<number | null>(null);

  const load = useCallback(() => {
    getExchangerBot()
      .then(setBot)
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Только владелец финансов"));
    getExchangerBotMembers().then((r) => setMembers(asRows(r, "items"))).catch(() => undefined);
    listExchangerBotBroadcasts().then((r) => setJobs(asRows(r, "items"))).catch(() => undefined);
    getExternalExchangers().then((r) => setShops(asRows(r, "exchangers", "items"))).catch(() => undefined);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function connect() {
    setBusy(true);
    try {
      setBot(await putExchangerBotToken(token.trim()));
      setToken("");
      toast.success("Бот подключён");
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось подключить бота");
    } finally {
      setBusy(false);
    }
  }

  async function addMember() {
    const id = Number(tgId);
    const exchangerId = Number(shopId);
    if (!id || !exchangerId) return toast.error("Укажите telegram id и магазин");
    setBusy(true);
    try {
      await createExchangerBotMember({ telegram_user_id: id, exchanger_id: exchangerId, role, label: label.trim() || undefined });
      setTgId("");
      setLabel("");
      toast.success("Доступ выдан");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось добавить");
    } finally {
      setBusy(false);
    }
  }

  const memberCols: Column<Dict>[] = [
    { key: "telegram_user_id", label: "Telegram id", render: (r) => <span className="font-mono">{String(r.telegram_user_id)}</span> },
    { key: "exchanger_name", label: "Магазин", render: (r) => String(r.exchanger_name ?? r.exchanger_id ?? "—") },
    { key: "role", label: "Роль", render: (r) => <Badge tone={r.role === "owner" ? "green" : "default"}>{r.role === "owner" ? "владелец" : "сотрудник"}</Badge> },
    { key: "label", label: "Пометка", render: (r) => String(r.label ?? "—") },
    { key: "is_active", label: "Статус", render: (r) => <Badge tone={r.is_active ? "green" : "red"}>{r.is_active ? "вкл" : "выкл"}</Badge> },
    {
      key: "id",
      label: "",
      render: (r) => (
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => patchExchangerBotMember(Number(r.id), { is_active: !r.is_active }).then(load)}>
            {r.is_active ? "Отключить" : "Включить"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => deleteExchangerBotMember(Number(r.id)).then(load)}>Удалить</Button>
        </div>
      ),
    },
  ];

  const jobCols: Column<Dict>[] = [
    { key: "id", label: "#", width: "60px", render: (r) => <span className="font-mono">{String(r.id)}</span> },
    { key: "audience", label: "Аудитория" },
    { key: "status", label: "Статус", render: (r) => <Badge tone="default">{String(r.status)}</Badge> },
    { key: "sent_count", label: "Отправлено", render: (r) => `${r.sent_count ?? 0} / ${r.total_count ?? 0}` },
    { key: "failed_count", label: "Ошибки", render: (r) => String(r.failed_count ?? 0) },
    {
      key: "cancel",
      label: "",
      render: (r) =>
        r.status === "running" || r.status === "pending" ? (
          <Button size="sm" variant="ghost" onClick={() => cancelExchangerBotBroadcast(Number(r.id)).then(load)}>Отменить</Button>
        ) : null,
    },
  ];

  return (
    <>
      <PageHeader
        title="Бот внештатников"
        subtitle="Один бот на всех магазинов. Вставьте токен — вебхук и команды встанут сами. Доступ по telegram id."
        actions={
          <Button variant="ghost" onClick={load}><RefreshCw size={16} /> Обновить</Button>
        }
      />
      <div className="flex flex-col gap-5">
        <Card>
          <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold">
            <Bot size={16} /> Подключение
          </div>
          {bot?.configured ? (
            <div className="flex flex-col gap-3">
              <div className="text-[13px]">
                Бот: <span className="font-mono">@{String(bot.bot_username ?? "—")}</span>
                <div className="mt-1 text-[var(--text-muted)]">Токен {String(bot.token_masked ?? "—")}</div>
                <div className="mt-1 text-[var(--text-muted)]">Вебхук {String(bot.webhook_url ?? "—")}</div>
                {Boolean(bot.last_error) && <div className="mt-1 text-[var(--red)]">{String(bot.last_error)}</div>}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => reconfigureExchangerBot().then(setBot).then(() => toast.success("Вебхук обновлён"))}>Перенастроить</Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => deleteExchangerBotToken().then(setBot).then(() => toast.success("Бот отключён"))}>Отключить</Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Токен бота от @BotFather">
                <Input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="1234567890:AAE…" className="font-mono w-80" />
              </Field>
              <Button variant="primary" disabled={busy || token.trim().length < 20} onClick={connect}>Проверить и подключить</Button>
            </div>
          )}
        </Card>

        <Card>
          <div className="mb-3 text-[13px] font-semibold">Доступы</div>
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <Field label="Telegram id">
              <Input value={tgId} onChange={(e) => setTgId(e.target.value)} placeholder="14114102312130" className="font-mono" />
            </Field>
            <Field label="Магазин">
              <select className="h-9 rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 text-[13px]" value={shopId} onChange={(e) => setShopId(e.target.value)}>
                <option value="">Выберите</option>
                {shops.map((s) => (
                  <option key={String(s.id)} value={String(s.id)}>{String(s.name ?? s.id)}</option>
                ))}
              </select>
            </Field>
            <Field label="Роль">
              <select className="h-9 rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 text-[13px]" value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="owner">владелец</option>
                <option value="clerk">сотрудник</option>
              </select>
            </Field>
            <Field label="Пометка">
              <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="необязательно" />
            </Field>
            <Button variant="primary" disabled={busy} onClick={addMember}>Выдать</Button>
          </div>
          <Table columns={memberCols} rows={members} empty="Никого нет — выдайте первый telegram id" />
        </Card>

        <Card>
          <div className="mb-3 text-[13px] font-semibold">Рассылка</div>
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <Field label="Аудитория">
              <select className="h-9 rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 text-[13px]" value={audience} onChange={(e) => { setAudience(e.target.value); setPreviewCount(null); }}>
                <option value="all">все</option>
                <option value="owners">владельцы</option>
                <option value="clerks">сотрудники</option>
              </select>
            </Field>
            <Button size="sm" variant="ghost" onClick={() => previewExchangerBotBroadcast(audience).then((r) => setPreviewCount(Number(r.count ?? 0)))}>
              Получателей{previewCount != null ? `: ${previewCount}` : ""}
            </Button>
          </div>
          <Field label="Текст">
            <textarea className="min-h-24 w-full rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-3 text-[13px]" value={broadcastText} onChange={(e) => setBroadcastText(e.target.value)} />
          </Field>
          <div className="mt-3">
            <Button
              variant="primary"
              disabled={busy || !broadcastText.trim()}
              onClick={() => createExchangerBotBroadcast({ audience, text: broadcastText.trim() }).then(() => { toast.success("Рассылка запущена"); setBroadcastText(""); load(); })}
            >
              Отправить
            </Button>
          </div>
          <div className="mt-4">
            <Table columns={jobCols} rows={jobs} empty="Рассылок ещё не было" />
          </div>
        </Card>
      </div>
    </>
  );
}
