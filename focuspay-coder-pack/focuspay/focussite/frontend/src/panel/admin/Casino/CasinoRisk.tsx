import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { RefreshCw } from "lucide-react";
import {
  getCasinoRisk,
  type AdminCasinoRisk,
  type AdminCasinoRiskPlayer,
  type AdminCasinoRiskWindow,
} from "@/panel/lib/adminApi";
import { PanelApiError } from "@/panel/lib/panelApi";
import { Badge, Button, Card, Input, Kpi, PageHeader } from "@/panel/ui/primitives";
import { CorridorChart, Gauge, corridorStatus } from "@/panel/ui/riskViz";

const WINDOWS: Array<{ id: AdminCasinoRiskWindow; label: string }> = [
  { id: "24h", label: "24ч" },
  { id: "7d", label: "7д" },
  { id: "30d", label: "30д" },
];

const GAME_LABEL: Record<string, string> = {
  pvp_dice: "Кубики",
  baccara: "Баккара",
  blackjack: "Блэкджек",
  raffle: "Раффл",
  cub: "Кубик vs дом",
  roulette: "Рулетка 0–36",
  holdem: "Холдем",
  russian_draughts: "Русские шашки",
  jackpot: "Джекпот",
  fixed_room: "Комнаты",
  clan_war: "Клан vs клан",
};

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof PanelApiError ? error.message : fallback;
}

function formatRub(value: number): string {
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}

function formatPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
}

function playerLabel(row: AdminCasinoRiskPlayer): string {
  return row.username ? `@${row.username}` : `ID ${row.telegram_id}`;
}

function toneOf(risk: string | undefined): "red" | "yellow" | "default" {
  if (risk === "high") return "red";
  if (risk === "medium") return "yellow";
  return "default";
}

export function CasinoRisk() {
  const [windowId, setWindowId] = useState<AdminCasinoRiskWindow>("7d");
  const [threshold, setThreshold] = useState("15");
  const [appliedThreshold, setAppliedThreshold] = useState(15);
  const [data, setData] = useState<AdminCasinoRisk | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [hidden, setHidden] = useState<Set<number>>(new Set());

  const load = useCallback(async (nextWindow = windowId, nextThreshold = appliedThreshold) => {
    setLoading(true);
    setError(null);
    try {
      const deviation = Number.isFinite(nextThreshold) && nextThreshold > 0 ? nextThreshold : 15;
      setAppliedThreshold(deviation);
      setData(await getCasinoRisk({ window: nextWindow, rtp_deviation_pp: deviation }));
      setSelected(new Set());
    } catch (loadError) {
      setData(null);
      setError(getErrorMessage(loadError, "Не удалось загрузить риск"));
    } finally {
      setLoading(false);
    }
  }, [appliedThreshold, windowId]);

  useEffect(() => {
    void load(windowId, appliedThreshold);
    // Window changes refetch. Threshold applies on blur / refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowId]);

  const visibleAnomalies = useMemo(
    () => (data?.anomalies ?? []).filter((row) => !hidden.has(row.telegram_id)),
    [data, hidden],
  );

  const gaugeMax = useMemo(() => {
    if (!data) return 1;
    const { available_rub, balance_rub, floor_rub, target_rub, max_payout_rub } = data.bankroll;
    return Math.max(available_rub, balance_rub, floor_rub, target_rub, max_payout_rub, 1);
  }, [data]);

  const playedGames = useMemo(() => (data?.games ?? []).filter((row) => row.rounds > 0), [data]);
  const idleGameNames = useMemo(
    () =>
      (data?.games ?? [])
        .filter((row) => row.rounds <= 0)
        .map((row) => GAME_LABEL[row.game_type] ?? row.game_type),
    [data],
  );

  const copySelected = async () => {
    const ids = visibleAnomalies.filter((row) => selected.has(row.telegram_id)).map((row) => String(row.telegram_id));
    if (!ids.length) return;
    await navigator.clipboard.writeText(ids.join("\n"));
  };

  const hideSelected = () => {
    setHidden((current) => {
      const next = new Set(current);
      for (const id of selected) next.add(id);
      return next;
    });
    setSelected(new Set());
  };

  return (
    <div className="mx-auto w-full max-w-[1100px] space-y-5">
      <PageHeader
        title="Казино — Риск"
        subtitle="Сколько в кассе, кто сейчас должен игрокам, и не уехала ли отдача игр от формулы"
        actions={
          <Button
            type="button"
            size="sm"
            onClick={() => {
              const parsed = Number(threshold);
              void load(windowId, Number.isFinite(parsed) && parsed > 0 ? parsed : 15);
            }}
            disabled={loading}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
            Обновить
          </Button>
        }
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex gap-1">
          {WINDOWS.map((item) => (
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
        <label className="flex flex-col gap-1 text-[12px] text-[var(--text-muted)]">
          Порог отклонения RTP (п.п.)
          <Input
            className="h-8 w-24"
            type="number"
            min={1}
            max={100}
            step="1"
            value={threshold}
            onChange={(event) => setThreshold(event.target.value)}
            onBlur={() => {
              const parsed = Number(threshold);
              void load(windowId, Number.isFinite(parsed) && parsed > 0 ? parsed : 15);
            }}
          />
        </label>
      </div>

      {loading ? (
        <Card className="py-12 text-center text-[13px] text-[var(--text-muted)]" aria-busy="true">
          Загрузка риска…
        </Card>
      ) : error ? (
        <Card className="space-y-3">
          <div role="alert" className="text-[13px] text-[var(--red)]">
            {error}
          </div>
          <Button
            type="button"
            size="sm"
            onClick={() => {
              const parsed = Number(threshold);
              void load(windowId, Number.isFinite(parsed) && parsed > 0 ? parsed : 15);
            }}
          >
            Повторить
          </Button>
        </Card>
      ) : !data ? (
        <Card className="py-12 text-center text-[13px] text-[var(--text-muted)]">Данные не получены</Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div data-risk-verify="window_bet_rub">
              <Kpi
                label="Ставки за окно"
                value={formatRub(data.verify.value_rub)}
                hint="все заявки, без фильтра статуса"
              />
            </div>
            <Kpi
              label="Открыто к банку"
              value={data.exposure.pct_of_bank == null ? "нет банка" : formatPct(data.exposure.pct_of_bank)}
              hint="сколько должны игрокам относительно кассы"
            />
            <Kpi
              label="Открытые PvP"
              value={formatRub(data.exposure.open_pvp_banks_rub)}
              hint="банки дуэлей waiting/active"
            />
            <Kpi
              label="Долг дома"
              value={formatRub(data.exposure.house_liability_rub)}
              hint="активные резервы против казино"
            />
          </div>
          <details className="text-[12px] text-[var(--text-muted)]">
            <summary className="cursor-pointer select-none">Как посчитаны ставки за окно</summary>
            <p className="mt-2">
              Сумма всех ставок за выбранное окно, без фильтра статуса. RTP и таблица игр ниже — только завершённые
              партии.
            </p>
            <p className="mt-1 font-mono text-[11px]" data-risk-verify-sql="">
              {data.verify.sql}
            </p>
          </details>

          <Card className="space-y-4">
            <div>
              <h2 className="text-[14px] font-semibold">Банк казино</h2>
              <p className="mt-1 text-[12px] text-[var(--text-muted)]">
                Доступно = баланс минус резерв. Риски слева направо: порог (минимум), макс. выплата за одну игру, цель
                (2× порог). Полоса заполнена, если касса выше этих меток.
              </p>
            </div>
            <Gauge
              value={data.bankroll.available_rub}
              max={gaugeMax}
              label="Доступно сейчас"
              warnAt={data.bankroll.floor_rub || undefined}
              dangerAt={data.bankroll.floor_rub ? data.bankroll.floor_rub * 0.5 : undefined}
              markers={[
                { value: data.bankroll.floor_rub, label: "порог" },
                { value: data.bankroll.max_payout_rub, label: "макс. выплата" },
                { value: data.bankroll.target_rub, label: "цель" },
              ]}
              format={formatRub}
            />
            <dl className="grid gap-x-6 gap-y-2 text-[13px] sm:grid-cols-2 lg:grid-cols-3">
              <div className="flex justify-between gap-3">
                <dt className="text-[var(--text-muted)]">Баланс</dt>
                <dd className="font-mono tabular-nums">{formatRub(data.bankroll.balance_rub)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-[var(--text-muted)]">В резерве</dt>
                <dd className="font-mono tabular-nums">{formatRub(data.bankroll.reserved_rub)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-[var(--text-muted)]">Потолок одной выплаты</dt>
                <dd className="font-mono tabular-nums">
                  {formatRub(data.bankroll.max_payout_rub)}
                  <span className="ml-1 text-[11px] text-[var(--text-muted)]">
                    {formatPct(data.bankroll.max_profit_pct_per_round)} кассы
                  </span>
                </dd>
              </div>
              <div className="flex justify-between gap-3 sm:col-span-2 lg:col-span-3">
                <dt className="text-[var(--text-muted)]">Теория PvP после отыгрыша</dt>
                <dd className="font-mono tabular-nums">
                  {formatPct(
                    data.games.find((row) => row.game_type === "pvp_dice")?.theoretical_rtp_pct ??
                      100 - data.commission_complete_percent / 2,
                  )}{" "}
                  при комиссии {formatPct(data.commission_complete_percent)}
                </dd>
              </div>
            </dl>
          </Card>

          <Card className="space-y-3">
            <h2 className="text-[14px] font-semibold">Отдача игр (RTP)</h2>
            <p className="text-[12px] text-[var(--text-muted)]">
              Точка — сколько реально вернули игрокам. Пунктир — сколько должны по формуле. Серая полоса — шум при
              текущем числе партий (±100/√n). Мало партий — широкая полоса, это не сломанная игра. Точка правее полосы
              — игроки выигрывают больше расчёта.
            </p>
            <CorridorChart
              labels={playedGames.map((row) => GAME_LABEL[row.game_type] ?? row.game_type)}
              actual={playedGames.map((row) => row.actual_rtp_pct)}
              expected={playedGames.map((row) => row.theoretical_rtp_pct)}
              corridorLow={playedGames.map((row) => row.corridor_low_pct)}
              corridorHigh={playedGames.map((row) => row.corridor_high_pct)}
              rounds={playedGames.map((row) => row.rounds)}
              format={(value) => `${value.toFixed(0)}%`}
            />
            {playedGames.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[12.5px]">
                  <thead className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">
                    <tr>
                      <th className="py-1">Игра</th>
                      <th className="py-1">Партий</th>
                      <th className="py-1">Вернули игрокам</th>
                      <th className="py-1">По формуле</th>
                      <th className="py-1">Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {playedGames.map((row) => {
                      const status = corridorStatus(
                        row.actual_rtp_pct,
                        row.corridor_low_pct,
                        row.corridor_high_pct,
                        row.rounds,
                      );
                      return (
                        <tr key={row.game_type} className="border-t border-[var(--border)]">
                          <td className="py-1.5">{GAME_LABEL[row.game_type] ?? row.game_type}</td>
                          <td className="py-1.5 font-mono">{row.rounds}</td>
                          <td className="py-1.5 font-mono">{formatPct(row.actual_rtp_pct)}</td>
                          <td className="py-1.5 font-mono">{formatPct(row.theoretical_rtp_pct)}</td>
                          <td className="py-1.5 text-[12px] text-[var(--text-muted)]">{status.label}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
            {idleGameNames.length ? (
              <p className="text-[12px] text-[var(--text-muted)]">Без партий за окно: {idleGameNames.join(", ")}</p>
            ) : null}
          </Card>

          <Card className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-[14px] font-semibold">Аномалии</h2>
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" variant="ghost" onClick={() => void copySelected()} disabled={!selected.size}>
                  Скопировать ID
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={hideSelected} disabled={!selected.size}>
                  Скрыть выбранные
                </Button>
                {selected.size === 1 ? (
                  <Link
                    to={`/x8/users?user=${[...selected][0]}`}
                    className="inline-flex h-8 items-center rounded-[var(--radius)] border border-[var(--border-strong)] px-3 text-[12.5px]"
                  >
                    Открыть пользователя
                  </Link>
                ) : null}
              </div>
            </div>
            <p className="text-[12px] text-[var(--text-muted)]">
              Игрок, чья отдача уехала от формулы игры больше чем на {appliedThreshold} п.п. Красный — от порога и выше,
              жёлтый — от половины. «Скрыть» только на этом экране, до обновления.
            </p>
            {visibleAnomalies.length === 0 ? (
              <p className="py-6 text-center text-[13px] text-[var(--text-muted)]">Нет строк выше порога</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[12.5px]">
                  <thead className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">
                    <tr>
                      <th className="py-1 pr-2">
                        <input
                          type="checkbox"
                          checked={visibleAnomalies.every((row) => selected.has(row.telegram_id))}
                          onChange={(event) => {
                            setSelected(
                              event.target.checked
                                ? new Set(visibleAnomalies.map((row) => row.telegram_id))
                                : new Set(),
                            );
                          }}
                        />
                      </th>
                      <th className="py-1">Игрок</th>
                      <th className="py-1">n</th>
                      <th className="py-1">RTP игрока</th>
                      <th className="py-1">RTP игры</th>
                      <th className="py-1">Δ</th>
                      <th className="py-1">Нетто</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleAnomalies.map((row) => (
                      <tr key={row.telegram_id} className="border-t border-[var(--border)]">
                        <td className="py-1.5 pr-2">
                          <input
                            type="checkbox"
                            checked={selected.has(row.telegram_id)}
                            onChange={(event) => {
                              setSelected((current) => {
                                const next = new Set(current);
                                if (event.target.checked) next.add(row.telegram_id);
                                else next.delete(row.telegram_id);
                                return next;
                              });
                            }}
                          />
                        </td>
                        <td className="py-1.5">{playerLabel(row)}</td>
                        <td className="py-1.5 font-mono">{row.rounds}</td>
                        <td className="py-1.5 font-mono">{formatPct(row.player_rtp_pct)}</td>
                        <td className="py-1.5 font-mono">{formatPct(row.game_rtp_pct)}</td>
                        <td className="py-1.5">
                          <Badge tone={toneOf(row.risk)}>{formatPct(row.delta_pp)}</Badge>
                        </td>
                        <td className="py-1.5 font-mono">{formatRub(row.net_rub)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <LeaderCard title="Топ выигравших" rows={data.winners} empty="Нет выигравших за окно" />
            <LeaderCard title="Топ проигравших" rows={data.losers} empty="Нет проигравших за окно" />
          </div>
        </>
      )}
    </div>
  );
}

function LeaderCard({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: AdminCasinoRiskPlayer[];
  empty: string;
}) {
  return (
    <Card className="space-y-3">
      <h2 className="text-[14px] font-semibold">{title}</h2>
      {rows.length === 0 ? (
        <p className="py-6 text-center text-[13px] text-[var(--text-muted)]">{empty}</p>
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {rows.map((row) => (
            <div key={row.telegram_id} className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <div className="truncate text-[13px]">{playerLabel(row)}</div>
                <div className="text-[11px] text-[var(--text-muted)]">
                  RTP {formatPct(row.player_rtp_pct)} vs игры {formatPct(row.game_rtp_pct)} · n={row.rounds}
                </div>
              </div>
              <div className="shrink-0 font-mono text-[13px]">{formatRub(row.net_rub)}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
