import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { getBalances, type Dict } from "@/panel/lib/adminApi";
import { Badge, Card, Field, Input, Kpi, PageHeader, Table, type Column } from "@/panel/ui/primitives";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}

export function AdminBalances() {
  const navigate = useNavigate();
  const [data, setData] = useState<Dict | null>(null);
  const [loading, setLoading] = useState(true);
  const [userSearch, setUserSearch] = useState("");
  const [partnerSearch, setPartnerSearch] = useState("");
  const [userPage, setUserPage] = useState(1);
  const [partnerPage, setPartnerPage] = useState(1);

  const load = useCallback(() => {
    setLoading(true);
    getBalances(1, 500)
      .then(setData)
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(), [load]);

  const totals = (data?.totals ?? {}) as Dict;
  const users = (data?.users ?? []) as Dict[];
  const partners = (data?.partners ?? []) as Dict[];
  const PAGE_SIZE = 20;
  const filteredUsers = users.filter((row) => `${row.user_id ?? ""} ${row.username ?? ""} ${row.first_name ?? ""}`.toLowerCase().includes(userSearch.trim().toLowerCase()));
  const filteredPartners = partners.filter((row) => `${row.code ?? ""} ${row.name ?? ""}`.toLowerCase().includes(partnerSearch.trim().toLowerCase()));
  const userPages = Math.max(1, Math.ceil(filteredUsers.length / PAGE_SIZE));
  const partnerPages = Math.max(1, Math.ceil(filteredPartners.length / PAGE_SIZE));
  const visibleUsers = filteredUsers.slice((userPage - 1) * PAGE_SIZE, userPage * PAGE_SIZE);
  const visiblePartners = filteredPartners.slice((partnerPage - 1) * PAGE_SIZE, partnerPage * PAGE_SIZE);

  const mono = (v: unknown) => <span className="font-mono tabular-nums">{money(v)}</span>;

  const userCols: Column<Dict>[] = [
    { key: "user_id", label: "ID", width: "90px", render: (r) => <span className="font-mono">{String(r.user_id ?? "—")}</span> },
    { key: "username", label: "Пользователь", render: (r) => (
      <button type="button" className="text-left text-[var(--accent)] hover:underline" onClick={(e) => { e.stopPropagation(); navigate(`/x8/users?user=${r.user_id}`); }}>
        {r.username ? `@${String(r.username)}` : String(r.first_name || r.user_id || "—")}
      </button>
    ) },
    { key: "cashback_rub", label: "Кэшбэк ₽", align: "right", render: (r) => mono(r.cashback_rub) },
    { key: "referral_rub", label: "Реферальный ₽", align: "right", render: (r) => mono(r.referral_rub) },
    { key: "balance_rub", label: "Баланс ₽", align: "right", render: (r) => mono(r.balance_rub) },
    { key: "available_rub", label: "Доступно ₽", align: "right", render: (r) => mono(r.available_rub) },
    { key: "pending_withdraw_rub", label: "К выводу ₽", align: "right", render: (r) => mono(r.pending_withdraw_rub) },
  ];

  const partnerCols: Column<Dict>[] = [
    { key: "code", label: "Код", render: (r) => (
      <button type="button" className="font-mono text-[var(--accent)] hover:underline" onClick={(e) => { e.stopPropagation(); if (r.campaign_id != null) navigate(`/x8/partners/${r.campaign_id}`); }}>
        {String(r.code ?? "—")}
      </button>
    ) },
    { key: "name", label: "Название", render: (r) => String(r.name ?? "—") },
    { key: "balance_rub", label: "Баланс ₽", align: "right", render: (r) => mono(r.balance_rub) },
    {
      key: "is_active",
      label: "Статус",
      width: "110px",
      render: (r) => <Badge tone={r.is_active ? "green" : "default"}>{r.is_active ? "активен" : "выключен"}</Badge>,
    },
  ];

  return (
    <>
      <PageHeader title="Балансы" subtitle="Балансы пользователей и партнёров" />

      <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-3 max-[640px]:grid-cols-2 max-[420px]:grid-cols-1">
        <Kpi label="Кешбэк всего, ₽" value={money(totals.users_cashback_rub)} />
        <Kpi label="Рефералка всего, ₽" value={money(totals.users_referral_rub)} />
        <Kpi label="Балансы юзеров, ₽" value={money(totals.users_balance_rub)} />
        <Kpi label="Доступно юзерам, ₽" value={money(totals.users_available_rub)} />
        <Kpi label="К выводу, ₽" value={money(totals.pending_withdrawals_rub)} />
        <Kpi label="Балансы партнёров, ₽" value={money(totals.partners_balance_rub)} />
        <Kpi label="Обязательства, ₽" value={money(totals.liabilities_rub)} />
      </div>

      <Card>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div className="text-[13.5px] font-semibold">Пользователи</div>
          <Field label="Поиск"><Input value={userSearch} onChange={(e) => { setUserSearch(e.target.value); setUserPage(1); }} placeholder="ID / username" className="w-[220px]" /></Field>
        </div>
        <Table columns={userCols} rows={visibleUsers} empty={loading ? "Загрузка…" : "Нет данных"} onRowClick={(r) => navigate(`/x8/users?user=${r.user_id}`)} />
        <Pager page={userPage} pages={userPages} onPage={setUserPage} count={filteredUsers.length} />
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div className="text-[13.5px] font-semibold">Партнёры</div>
          <Field label="Поиск"><Input value={partnerSearch} onChange={(e) => { setPartnerSearch(e.target.value); setPartnerPage(1); }} placeholder="Код / название" className="w-[220px]" /></Field>
        </div>
        <Table columns={partnerCols} rows={visiblePartners} empty={loading ? "Загрузка…" : "Нет данных"} onRowClick={(r) => r.campaign_id != null && navigate(`/x8/partners/${r.campaign_id}`)} />
        <Pager page={partnerPage} pages={partnerPages} onPage={setPartnerPage} count={filteredPartners.length} />
      </Card>
    </>
  );
}

function Pager({ page, pages, count, onPage }: { page: number; pages: number; count: number; onPage: (page: number) => void }) {
  return (
    <div className="mt-4 flex items-center justify-between text-[12px] text-[var(--text-muted)]">
      <span>{count} записей · стр. {page}/{pages}</span>
      <div className="flex items-center gap-2">
        <button type="button" disabled={page <= 1} onClick={() => onPage(Math.max(1, page - 1))} className="rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-1.5 disabled:opacity-40">Назад</button>
        <button type="button" disabled={page >= pages} onClick={() => onPage(Math.min(pages, page + 1))} className="rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-1.5 disabled:opacity-40">Вперёд</button>
      </div>
    </div>
  );
}
