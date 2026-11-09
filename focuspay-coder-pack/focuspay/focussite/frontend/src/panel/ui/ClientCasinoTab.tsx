import { Link } from "react-router-dom";
import { Badge, Button, Card, Table, type BadgeTone, type Column } from "@/panel/ui/primitives";
import type {
  CasinoClientGame,
  CasinoClientProfile,
  CasinoClientScope,
  CasinoClientWithdrawal,
} from "@/panel/lib/casinoClientProfile";

function money(value: unknown, digits = 2) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits }).format(Number(value ?? 0));
}

function dt(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function riskTone(value: unknown): BadgeTone {
  const risk = String(value ?? "");
  if (risk === "high") return "red";
  if (risk === "medium") return "yellow";
  if (risk === "low") return "green";
  return "default";
}

function statusTone(status: unknown, phase?: unknown): BadgeTone {
  const value = String(phase || status || "");
  if (value === "completed" || value === "paid") return "green";
  if (value === "pending" || value === "awaiting") return "blue";
  if (value === "processing") return "yellow";
  if (value === "rejected") return "red";
  if (value === "canceled") return "default";
  return "default";
}

function Info({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className={mono ? "mt-0.5 font-mono text-[13px]" : "mt-0.5 text-[13px]"}>{value}</div>
    </div>
  );
}

export function ClientCasinoTab({
  data,
  scope,
  loading,
  error,
  emptyLabel = "В казино не играл",
  onLoadMore,
  loadingMore,
  gamesHref,
}: {
  data: CasinoClientProfile | null;
  scope: CasinoClientScope;
  loading?: boolean;
  error?: string | null;
  emptyLabel?: string;
  onLoadMore?: () => void;
  loadingMore?: boolean;
  gamesHref?: string;
}) {
  if (loading) {
    return <Card data-client-casino-tab="loading">Загрузка казино…</Card>;
  }
  if (error) {
    return (
      <Card data-client-casino-tab="error">
        <p className="text-[13px] text-[var(--red)]">{error}</p>
      </Card>
    );
  }
  if (!data) {
    return (
      <Card data-client-casino-tab="empty">
        <p className="text-[13px] text-[var(--text-muted)]">{emptyLabel}</p>
      </Card>
    );
  }

  const player = data.player ?? {};
  const level = data.level ?? {};
  const wagering = data.wagering ?? {};
  const rail = data.payout_rail ?? {};
  const raffle = data.raffle ?? {};
  const games = (data.recent_games ?? []) as CasinoClientGame[];
  const withdrawals = (data.withdrawals ?? []) as CasinoClientWithdrawal[];
  const byGame = data.wager_by_game ?? [];
  const risk = scope === "admin" ? data.risk : null;
  const locked = Number(wagering.locked_rub ?? 0);
  const remainingStake = Number(wagering.remaining_rub ?? wagering.remaining_stake_rub ?? 0);
  const remainingRail = Number(rail.remaining_rub ?? 0);
  const cryptoAllowed = rail.crypto_allowed !== false;

  const gameCols: Column<CasinoClientGame>[] = [
    { key: "label", label: "Игра", render: (row) => String(row.label ?? row.game_type ?? "—") },
    { key: "result_label", label: "Исход", render: (row) => String(row.result_label ?? row.result ?? "—") },
    {
      key: "stake_rub",
      label: "Ставка",
      width: "110px",
      align: "right",
      render: (row) => <span className="font-mono">{row.stake_rub != null ? `${money(row.stake_rub)} ₽` : "—"}</span>,
    },
    { key: "settled_at", label: "Когда", width: "130px", render: (row) => dt(row.settled_at) },
  ];

  const wdCols: Column<CasinoClientWithdrawal>[] = [
    { key: "id", label: "#", width: "70px", render: (row) => <span className="font-mono">{String(row.id ?? "—")}</span> },
    {
      key: "amount_rub",
      label: "₽",
      width: "110px",
      align: "right",
      render: (row) => <span className="font-mono">{money(row.amount_rub)}</span>,
    },
    {
      key: "method",
      label: "Куда",
      render: (row) => (row.method === "crypto" ? String(row.crypto ?? "crypto").toUpperCase() : "Карта"),
    },
    {
      key: "status",
      label: "Статус",
      width: "120px",
      render: (row) => (
        <Badge tone={statusTone(row.status, row.phase)}>
          {String(row.status_label ?? row.status ?? "—")}
        </Badge>
      ),
    },
    { key: "created_at", label: "Дата", width: "130px", render: (row) => dt(row.created_at) },
  ];

  return (
    <div className="flex flex-col gap-4" data-client-casino-tab={scope}>
      <Card>
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[13.5px] font-semibold">{String(player.display_name ?? `ID ${data.player_id ?? "—"}`)}</div>
            <div className="mt-0.5 text-[12px] text-[var(--text-muted)]">
              Уровень {String(level.index ?? "—")}
              {data.registered_at ? ` · в казино с ${data.registered_at}` : ""}
            </div>
          </div>
          {gamesHref ? (
            <Link className="text-[13px] text-[var(--accent)] hover:underline" to={gamesHref}>
              Игры этого игрока
            </Link>
          ) : null}
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-3 max-lg:grid-cols-1" data-client-casino-money>
        <Info label="Доступно, ₽" value={money(data.available_rub)} mono />
        <Info
          label="Отыгрыш"
          value={locked > 0 ? `заперто ${money(locked)} ₽ · ещё ${money(remainingStake)} ₽ ставок` : "открыт"}
        />
        <Info
          label="Рельс на карту"
          value={
            remainingRail > 0.01
              ? `осталось ${money(remainingRail)} ₽`
              : cryptoAllowed
                ? "крипта разрешена"
                : "сначала карта"
          }
        />
        <Info
          label="Комиссия"
          value={`${String(data.commission_profile === "wagering_active" ? "до отыгрыша" : "после отыгрыша")} · ${String(data.commission_rate ?? "—")}%`}
        />
        <Info label="Кэшбэк" value={`${String(data.cashback_percent ?? "0")}%`} />
        <Info label="Оборот за всё, ₽" value={money(data.lifetime_wager_rub)} mono />
      </div>

      <Card>
        <div className="mb-2 text-[13.5px] font-semibold">FocusLucky</div>
        <div className="text-[13px] text-[var(--text-secondary)]">
          Билеты в текущей кампании: <span className="font-mono">{Number(raffle.tickets ?? 0)}</span>
          {raffle.status ? ` · ${String(raffle.status)}` : ""}
        </div>
      </Card>

      {byGame.length > 0 ? (
        <Card>
          <div className="mb-2 text-[13.5px] font-semibold">Оборот по играм за неделю</div>
          <ul className="m-0 list-none space-y-1 p-0 text-[13px]">
            {byGame.map((row) => (
              <li key={String(row.game_type)} className="flex justify-between gap-2">
                <span>{String(row.label ?? row.game_type ?? "—")}</span>
                <span className="font-mono">{money(row.wager_rub)} ₽</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">Выводы казино</div>
        <Table columns={wdCols} rows={withdrawals} empty="Выводов нет" />
      </Card>

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">История раундов</div>
        <Table columns={gameCols} rows={games} empty="Раундов нет" />
        {data.history_next_before && onLoadMore ? (
          <div className="mt-3">
            <Button variant="secondary" size="sm" disabled={loadingMore} onClick={onLoadMore}>
              {loadingMore ? "Загрузка…" : "Ещё"}
            </Button>
          </div>
        ) : null}
      </Card>

      {scope === "admin" ? (
        <div data-client-casino-risk>
          <Card>
            <div className="mb-2 text-[13.5px] font-semibold">Риск и RTP</div>
          {risk ? (
            <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
              <Info label="Окно" value={String(risk.window ?? "7d")} />
              <Info label="Раунды" value={String(risk.rounds ?? 0)} />
              <Info label="Оборот, ₽" value={money(risk.wager_rub)} mono />
              <Info label="Возврат, ₽" value={money(risk.returned_rub)} mono />
              <Info label="Нетто игрока, ₽" value={money(risk.net_rub)} mono />
              <Info label="Нетто дома, ₽" value={money(risk.house_net_rub)} mono />
              <Info
                label="RTP игрока"
                value={risk.player_rtp_pct == null ? "—" : `${Number(risk.player_rtp_pct).toFixed(2)}%`}
              />
              <Info
                label="Теория"
                value={risk.game_rtp_pct == null ? "—" : `${Number(risk.game_rtp_pct).toFixed(2)}%`}
              />
              <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5">
                <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Метка</div>
                <div className="mt-1">
                  <Badge tone={riskTone(risk.risk)}>
                    {risk.risk ? String(risk.risk) : "нет"}
                    {risk.delta_pp != null ? ` · Δ ${Number(risk.delta_pp).toFixed(2)} п.п.` : ""}
                  </Badge>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-[13px] text-[var(--text-muted)]">Недостаточно данных за окно.</p>
          )}
          </Card>
        </div>
      ) : null}
    </div>
  );
}
