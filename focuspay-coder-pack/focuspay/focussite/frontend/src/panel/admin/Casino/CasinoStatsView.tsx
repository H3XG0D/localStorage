import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { AdminCasinoStats, AdminCasinoRtpTone, AdminCasinoShareTable } from "@/panel/lib/adminApi";
import { LineAreaChart } from "@/panel/ui/LineAreaChart";
import { Badge, Card, Kpi, Table, cx, type Column } from "@/panel/ui/primitives";
import { dateShort, money, moneyRub, signedMoney } from "@/panel/admin/analytics/format";

const GAME_LABEL: Record<string, string> = {
  pvp_dice: "Кубики",
  baccara: "Баккара",
  blackjack: "Блэкджек",
  cub: "Кубик дома",
  roulette: "Рулетка",
  jackpot: "Джекпот",
  fixed_room: "Комнаты",
  raffle: "FocusLucky",
};

function gameLabel(type: string) {
  return GAME_LABEL[type] ?? type;
}

function pct(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(1).replace(/\.0$/, "")}%`;
}

function rtpTone(tone: AdminCasinoRtpTone | null | undefined): "green" | "yellow" | "red" | "default" {
  if (tone === "high") return "red";
  if (tone === "medium") return "yellow";
  if (tone === "low") return "green";
  return "default";
}

type WaterfallStep = { key: string; label: string; amount: number; kind: "flow" | "total" | "note" };

function ProfitWaterfall({ data }: { data: AdminCasinoStats }) {
  const br = data.ggr_breakdown;
  const costs = data.costs;
  const steps: WaterfallStep[] = [
    { key: "pvp", label: "Рейк PvP (без ботов)", amount: br.pvp_rake_rub, kind: "flow" },
    { key: "jp", label: "Рейк джекпота", amount: br.jackpot_rake_rub, kind: "flow" },
    { key: "rooms", label: "Рейк комнат (без ботов)", amount: br.rooms_rake_rub, kind: "flow" },
    { key: "bots", label: "P&L против ботов", amount: br.house_vs_bots_rub, kind: "flow" },
    { key: "ggr", label: "GGR", amount: data.volume.ggr_rub, kind: "total" },
    { key: "cb", label: "Кешбэк", amount: -costs.cashback_rub, kind: "flow" },
    { key: "bonus", label: "Бонусы", amount: -costs.bonus_rub, kind: "flow" },
    { key: "creator", label: "Доля создателей", amount: -costs.creator_share_rub, kind: "flow" },
    { key: "ref", label: "Рефералам", amount: -costs.referral_share_rub, kind: "flow" },
    { key: "ngr", label: "Чистая прибыль", amount: data.ngr_rub, kind: "total" },
  ];
  const visible = steps.filter((step) => step.kind === "total" || Math.abs(step.amount) > 0.009);
  const max = Math.max(...visible.map((step) => Math.abs(step.amount)), 1);
  return (
    <div className="flex flex-col gap-3">
      {visible.map((step) => (
        <div
          key={step.key}
          className="grid grid-cols-[minmax(140px,1fr)_minmax(120px,1.5fr)_auto] items-center gap-3 text-[12px]"
        >
          <span className={cx("truncate", step.kind === "total" && "font-semibold")}>{step.label}</span>
          <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-overlay)]">
            <div
              className={cx("h-full rounded-full", step.amount >= 0 ? "bg-[var(--green)]" : "bg-[var(--red)]")}
              style={{ width: `${Math.max((Math.abs(step.amount) / max) * 100, 2)}%` }}
            />
          </div>
          <span className={cx("font-mono", step.amount >= 0 ? "text-[var(--green)]" : "text-[var(--red)]")}>
            {signedMoney(step.amount)}
          </span>
        </div>
      ))}
      <p className="text-[11px] leading-5 text-[var(--text-muted)]">
        Рейк со столов с ботами уже внутри «P&L против ботов». Складывать его с рейком PvP нельзя: дом
        ставит свои деньги, и итог по такому раунду — это GGR раунда, а не отдельная комиссия сверху.
      </p>
    </div>
  );
}

function playerLabel(id: number | null | undefined, username: string | null | undefined) {
  if (username) return username.startsWith("@") ? username : `@${username}`;
  if (id) return `ID: ${id}`;
  return "—";
}

function PersonLink({
  id,
  username,
}: {
  id: number | null | undefined;
  username: string | null | undefined;
}) {
  const label = playerLabel(id ?? null, username ?? null);
  if (!id) {
    return <span className="truncate">{label}</span>;
  }
  return (
    <Link className="truncate text-[var(--accent)] hover:underline" to={`/x8/users?user=${id}`}>
      {label}
    </Link>
  );
}

const EMPTY_SHARE: AdminCasinoShareTable = {
  total_rub: 0,
  shown_rub: 0,
  hidden_count: 0,
  hidden_rub: 0,
  rows: [],
};

function ShareTableCard({
  title,
  hint,
  table,
  showSource,
  showLevel,
}: {
  title: string;
  hint: string;
  table: AdminCasinoShareTable | undefined;
  showSource?: boolean;
  showLevel?: boolean;
}) {
  const pack = table ?? EMPTY_SHARE;
  if (pack.total_rub < 0.01 && pack.rows.length === 0) return null;
  const cols: Column<(typeof pack.rows)[number] & { id: string }>[] = [
    {
      key: "to",
      label: "Кому",
      render: (row) => (
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <PersonLink id={row.recipient_id} username={row.recipient_username} />
          {showLevel && row.level ? <Badge>{row.level.toUpperCase()}</Badge> : null}
        </span>
      ),
    },
  ];
  if (showSource) {
    cols.push({
      key: "from",
      label: "С кого",
      render: (row) => <PersonLink id={row.source_player_id} username={row.source_username} />,
    });
  }
  cols.push({
    key: "games",
    label: "Игр",
    align: "right",
    render: (row) => row.games.toLocaleString("ru-RU"),
  });
  cols.push({
    key: "amount_rub",
    label: "Сумма",
    align: "right",
    render: (row) => moneyRub(row.amount_rub, true),
  });
  const rows = pack.rows.map((row, index) => ({
    ...row,
    id: `${row.recipient_id ?? "x"}-${row.source_player_id ?? "x"}-${row.level ?? ""}-${index}`,
  }));
  return (
    <Card className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[14px] font-semibold">{title}</h2>
          <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">{hint}</p>
        </div>
        <div className="shrink-0 font-mono text-[13px] font-semibold tabular-nums">{moneyRub(pack.total_rub, true)}</div>
      </div>
      <Table columns={cols} rows={rows} empty="За период начислений нет" />
      {pack.hidden_count > 0 || pack.hidden_rub > 0.009 ? (
        <p className="text-[11px] text-[var(--text-muted)]">
          ещё {pack.hidden_count.toLocaleString("ru-RU")} строк · {moneyRub(pack.hidden_rub, true)} не в таблице
        </p>
      ) : null}
    </Card>
  );
}

function ShareTables({ data }: { data: AdminCasinoStats }) {
  const dist = data.distributions;
  if (!dist) return null;
  const visible =
    (dist.referrals?.total_rub ?? 0) > 0.009 ||
    (dist.creators?.total_rub ?? 0) > 0.009 ||
    (dist.cashback?.total_rub ?? 0) > 0.009 ||
    (dist.bonuses?.total_rub ?? 0) > 0.009;
  if (!visible) return null;
  return (
    <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
      <ShareTableCard
        title="Рефералам"
        hint="L1/L2 с игры игрока. Только casino_games — как строка водопада."
        table={dist.referrals}
        showSource
        showLevel
      />
      <ShareTableCard
        title="Доля создателя"
        hint="Партнёрская ссылка, не хост стола. С чьей игры срезали комиссию."
        table={dist.creators}
        showSource
      />
      <ShareTableCard title="Кешбэк" hint="Начислено игрокам за период" table={dist.cashback} />
      <ShareTableCard title="Бонусы" hint="Уровни оборота за период" table={dist.bonuses} />
    </div>
  );
}

export function CasinoStatsView({ data }: { data: AdminCasinoStats }) {
  const [hover, setHover] = useState<number | null>(null);
  const volume = data.volume;
  const rec = data.reconciliation;
  const diff = Math.abs(rec.diff_rub);
  const points = data.daily;
  const chartHandle = useMemo(() => points.reduce((sum, row) => sum + row.handle_rub, 0), [points]);
  const chartGgr = useMemo(() => points.reduce((sum, row) => sum + row.ggr_rub, 0), [points]);

  const typeRows = data.by_type.map((row) => ({ ...row, id: row.game_type }));
  const typeCols: Column<(typeof typeRows)[number]>[] = [
    { key: "game_type", label: "Игра", render: (row) => gameLabel(row.game_type) },
    { key: "rounds", label: "Раундов", align: "right", render: (row) => row.rounds.toLocaleString("ru-RU") },
    { key: "handle_rub", label: "Оборот", align: "right", render: (row) => moneyRub(row.handle_rub, true) },
    { key: "player_payout_rub", label: "Выплаты", align: "right", render: (row) => moneyRub(row.player_payout_rub, true) },
    {
      key: "ggr_rub",
      label: "GGR",
      align: "right",
      render: (row) => <span className={row.ggr_rub >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>{signedMoney(row.ggr_rub)}</span>,
    },
    { key: "hold_pct", label: "Hold", align: "right", render: (row) => pct(row.hold_pct) },
    {
      key: "rtp_pct",
      label: "RTP",
      align: "right",
      render: (row) => (
        <span className="inline-flex items-center gap-1.5">
          {pct(row.rtp_pct)}
          {row.theoretical_rtp_pct != null ? (
            <Badge tone={rtpTone(row.rtp_tone)}>теор. {pct(row.theoretical_rtp_pct)}</Badge>
          ) : null}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      {diff > 0.05 ? (
        <Card className="border-[var(--yellow)]/30 text-[12px] text-[var(--text-secondary)]">
          Сверка GGR с леджером владельца: {moneyRub(rec.ggr_rub, true)} vs {moneyRub(rec.owner_profit_rub, true)} (
          {signedMoney(rec.diff_rub)}). Цифры на этой странице — по живым раундам. Леджер остаётся контрольной
          лентой в Финансах.
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Оборот игроков" value={moneyRub(volume.handle_rub, true)} hint="Только живые ставки, без стейков ботов" />
        <Kpi label="Выплаты игрокам" value={moneyRub(volume.player_payout_rub, true)} />
        <Kpi
          label="GGR"
          value={moneyRub(volume.ggr_rub, true)}
          hint="Оборот минус выплаты. Рейк со столов с ботами уже внутри."
        />
        <Kpi label="Чистая прибыль" value={moneyRub(data.ngr_rub, true)} hint="GGR минус кешбэк, бонусы и доли" />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Hold" value={pct(volume.hold_pct)} hint="GGR / оборот" />
        <Kpi label="RTP" value={pct(volume.rtp_pct)} hint="Выплаты / оборот" />
        <Kpi label="Раундов" value={volume.rounds.toLocaleString("ru-RU")} />
        <Kpi label="Средняя ставка" value={volume.avg_bet_rub == null ? "—" : moneyRub(volume.avg_bet_rub, true)} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Активных игроков" value={data.players.active.toLocaleString("ru-RU")} hint="Уникальные за период" />
        <Kpi label="Новых игроков" value={data.players.new.toLocaleString("ru-RU")} hint="Первый раунд в периоде" />
        <Kpi
          label="Банк казино"
          value={moneyRub(data.bankroll.balance_rub, true)}
          hint="Сейчас, не за период"
        />
        <Kpi label="В резерве" value={moneyRub(data.bankroll.reserved_rub, true)} />
      </div>

      <div className="grid grid-cols-[minmax(0,1.45fr)_minmax(280px,1fr)] gap-4 max-[1050px]:grid-cols-1">
        <Card className="space-y-4">
          <div>
            <h2 className="text-[14px] font-semibold">Оборот и GGR по дням</h2>
            <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">Оборот — левая ось, GGR — правая</p>
          </div>
          <LineAreaChart
            points={points.map((point) => ({ key: point.date, label: dateShort(point.date) }))}
            series={[
              { key: "handle", label: "Оборот", color: "var(--blue)", values: points.map((p) => p.handle_rub) },
              {
                key: "ggr",
                label: "GGR",
                color: "var(--green)",
                values: points.map((p) => p.ggr_rub),
                fill: false,
                axis: "right",
              },
            ]}
            height={232}
            hover={hover}
            onHover={setHover}
            formatTick={(value) => money(value, true)}
            formatTickRight={(value) => money(value, true)}
            summary={`${moneyRub(chartHandle, true)} оборот · ${moneyRub(chartGgr, true)} GGR`}
            tooltip={(index) => {
              const point = points[index];
              return point ? (
                <div className="flex flex-col gap-0.5">
                  <span>{dateShort(point.date)}</span>
                  <span className="font-mono text-[var(--blue)]">{moneyRub(point.handle_rub, true)} оборот</span>
                  <span className="font-mono text-[var(--green)]">{moneyRub(point.ggr_rub, true)} GGR</span>
                </div>
              ) : null;
            }}
            emptyHint="Нет данных за период"
          />
        </Card>
        <Card className="space-y-3">
          <div>
            <h2 className="text-[14px] font-semibold">Откуда прибыль</h2>
            <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">Разложение GGR, затем расходы</p>
          </div>
          <ProfitWaterfall data={data} />
        </Card>
      </div>

      <ShareTables data={data} />

      <Card className="space-y-3">
        <h2 className="text-[14px] font-semibold">По играм</h2>
        <Table columns={typeCols} rows={typeRows} empty="Завершённых игр за период нет" />
      </Card>

      <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
        <Card className="space-y-3">
          <h2 className="text-[14px] font-semibold">Топ игроков</h2>
          {data.players.top.length === 0 ? (
            <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">Данных по игрокам пока нет</div>
          ) : (
            <div className="divide-y divide-[var(--border)]">
              {data.players.top.map((player, index) => (
                <div key={player.telegram_id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="w-6 shrink-0 text-[12px] text-[var(--text-muted)]">{index + 1}</span>
                    <div className="min-w-0">
                      <div className="truncate text-[13px] font-medium">
                        {player.username ? `@${player.username}` : `ID: ${player.telegram_id}`}
                      </div>
                      <div className="text-[12px] text-[var(--text-muted)]">
                        {player.rounds.toLocaleString("ru-RU")} игр · нетто {signedMoney(player.net_rub)}
                      </div>
                    </div>
                  </div>
                  <div className="shrink-0 font-mono text-[13px] font-semibold tabular-nums">
                    {moneyRub(player.handle_rub, true)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card className="space-y-3">
          <h2 className="text-[14px] font-semibold">Касса</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <Kpi label="Депозиты" value={moneyRub(data.cashier.deposited_rub, true)} hint={`${data.cashier.deposit_count} шт.`} />
            <Kpi label="Выводы (оплачено)" value={moneyRub(data.cashier.withdrawn_rub, true)} />
            <Kpi label="Выводы в очереди" value={moneyRub(data.cashier.pending_withdraw_rub, true)} />
            <Kpi
              label="Средний оборот на игрока"
              value={data.players.avg_handle_rub == null ? "—" : moneyRub(data.players.avg_handle_rub, true)}
            />
          </div>
        </Card>
      </div>
    </div>
  );
}
