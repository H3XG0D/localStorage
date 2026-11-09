import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { CopyField } from "@/panel/ui/CopyField";
import { useAuthedPoll } from "@/panel/lib/useAuthedPoll";
import { OpsClientLink, opsClientId } from "@/panel/lib/opsClientPath";
import {
  claimCasinoPayout,
  getCasinoPayouts,
  getMe,
  paidCasinoWithdrawal,
  payoutCasinoWithdrawal,
  rejectCasinoPayout,
  type CasinoPayoutRow,
  type OperatorMe,
} from "@/panel/lib/operatorApi";
import { Badge, Button, Card, Field, Input, PageHeader, cx } from "@/panel/ui/primitives";

function money(value: unknown): string {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value ?? 0));
}

function playerName(row: CasinoPayoutRow): string {
  const player = row.player;
  const fromChip = player && typeof player.display_name === "string" ? player.display_name : "";
  if (fromChip) return fromChip;
  if (row.player_username) return `@${row.player_username}`;
  if (row.player_first_name) return String(row.player_first_name);
  const id = payoutUserId(row);
  return `ID ${id ?? "—"}`;
}

function payoutUserId(row: CasinoPayoutRow): number | null {
  return opsClientId(row.player?.user_id ?? row.referrer_user_id);
}

function payoutMethodLabel(row: CasinoPayoutRow): string {
  return String(row.method ?? "") === "crypto" ? String(row.crypto ?? "crypto").toUpperCase() : "Карта";
}

function payoutFigures(row: CasinoPayoutRow): { amount: number; fee: number; payout: number } {
  const amount = Number(row.amount_rub ?? 0);
  const fee = Number(row.network_fee_rub ?? 0);
  const stored = row.payout_amount_rub;
  const hasStored = stored != null && stored !== "" && Number.isFinite(Number(stored));
  const payout = hasStored ? Number(stored) : Math.round((amount - fee) * 100) / 100;
  return { amount, fee, payout };
}

export function OperatorCasinoPayouts() {
  const [incoming, setIncoming] = useState<CasinoPayoutRow[]>([]);
  const [mine, setMine] = useState<CasinoPayoutRow[]>([]);
  const [team, setTeam] = useState<CasinoPayoutRow[]>([]);
  const [selId, setSelId] = useState<number | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [me, setMe] = useState<OperatorMe | null>(null);
  const [shiftLoaded, setShiftLoaded] = useState(false);
  const [searchParams] = useSearchParams();

  const load = useCallback(() => {
    setRefreshing(true);
    Promise.allSettled([getCasinoPayouts(), getMe()]).then(([payoutsResult, meResult]) => {
      if (payoutsResult.status === "fulfilled") {
        setIncoming(payoutsResult.value.incoming ?? []);
        setMine(payoutsResult.value.mine ?? []);
        setTeam(payoutsResult.value.team ?? []);
      } else {
        toast.error(
          payoutsResult.reason instanceof PanelApiError
            ? payoutsResult.reason.message
            : "Не удалось загрузить выплаты казино",
        );
      }
      if (meResult.status === "fulfilled") setMe(meResult.value);
      setLastUpdated(Date.now());
      setShiftLoaded(true);
    }).finally(() => {
      setLoading(false);
      setRefreshing(false);
    });
  }, []);

  useAuthedPoll("operator", load, 8000, [load]);

  const all = useMemo(() => {
    const seen = new Set<number>();
    const out: { group: string; item: CasinoPayoutRow }[] = [];
    for (const [group, list] of [
      ["Входящие", incoming],
      ["Мои", mine],
      ["Команда", team],
    ] as const) {
      for (const item of list) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        out.push({ group, item });
      }
    }
    return out;
  }, [incoming, mine, team]);

  const selected = all.find((row) => row.item.id === selId) ?? null;
  const requestedPayout = Number(searchParams.get("payout") ?? "");
  const shiftOpen = !!me?.active_shift;
  const shiftLocked = shiftLoaded && !shiftOpen;

  useEffect(() => {
    if (!Number.isInteger(requestedPayout) || requestedPayout <= 0) return;
    const match = all.find((row) => row.item.id === requestedPayout);
    if (match && match.item.id !== selId) setSelId(match.item.id);
  }, [all, requestedPayout, selId]);

  return (
    <>
      <PageHeader
        title="Выплаты казино"
        subtitle={`Входящих: ${incoming.length} · моих: ${mine.length} · у команды: ${team.length}`}
        actions={
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-[var(--text-muted)]" aria-live="polite">
              {refreshing
                ? "Обновление…"
                : lastUpdated
                  ? `Обновлено ${new Date(lastUpdated).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`
                  : "—"}
            </span>
            <Button size="sm" variant="ghost" onClick={load} disabled={refreshing} aria-label="Обновить выплаты">
              ↻
            </Button>
          </div>
        }
      />

      {shiftLocked && (
        <div className="rounded-[var(--radius-lg)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] px-4 py-3 text-[13px] text-[var(--yellow)]">
          Смена не открыта. Выплаты доступны для просмотра, рабочие действия разблокируются после открытия смены.
        </div>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)_420px] gap-4 max-lg:grid-cols-1" data-ops-casino-payouts="">
        <div className="flex flex-col gap-4">
          <Card className="p-0">
            <div className="max-h-[calc(100dvh-200px)] overflow-y-auto" data-ops-payout-list="">
              {all.length === 0 ? (
                <p className="p-8 text-center text-[13px] text-[var(--text-muted)]">{loading ? "Загрузка…" : "Выплат нет"}</p>
              ) : (
                all.map(({ group, item }) => (
                  <div
                    key={item.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelId(item.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelId(item.id);
                      }
                    }}
                    className={cx(
                      "flex w-full cursor-pointer items-center gap-3 border-b border-[var(--border)] px-4 py-3 text-left transition-colors last:border-0",
                      selId === item.id ? "bg-[var(--bg-elevated)]" : "hover:bg-[var(--bg-elevated)]",
                      shiftLocked && "opacity-60 grayscale-[.15]",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[13px] font-medium">#{item.id}</span>
                        <Badge tone={group === "Входящие" ? "blue" : group === "Мои" ? "yellow" : "default"}>
                          {group === "Входящие" ? "В ожидании" : group === "Мои" ? "На выплате" : group}
                        </Badge>
                      </div>
                      <div className="mt-0.5 truncate text-[12px] text-[var(--text-muted)]">
                        {payoutMethodLabel(item)}
                        {" · "}
                        <OpsClientLink userId={payoutUserId(item)} tab="casino">
                          {playerName(item)}
                        </OpsClientLink>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-[13px]">{money(payoutFigures(item).payout)} ₽</div>
                      <Badge tone={group === "Входящие" ? "blue" : group === "Мои" ? "yellow" : "default"}>
                        {payoutMethodLabel(item)}
                      </Badge>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>

        <div className="max-lg:order-first">
          {selected ? (
            <PayoutPanel
              row={selected.item}
              group={selected.group}
              shiftOpen={shiftLoaded && shiftOpen}
              onChanged={load}
            />
          ) : (
            <Card>
              <p className="py-12 text-center text-[13px] text-[var(--text-muted)]">Выберите выплату</p>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function PayoutPanel({
  row,
  group,
  shiftOpen,
  onChanged,
}: {
  row: CasinoPayoutRow;
  group: string;
  shiftOpen: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [tx, setTx] = useState("");
  const method = String(row.method ?? "");
  const isCrypto = method === "crypto";
  const player = row.player ?? {};
  const locked = Number(player.wagering?.locked_rub ?? 0);
  const remainingRail = Number(player.payout_rail?.remaining_rub ?? 0);
  const cryptoAllowed = player.payout_rail?.crypto_allowed !== false;
  const actionDisabled = busy || !shiftOpen;
  const userId = payoutUserId(row);
  const mode = group === "Входящие" ? "incoming" : group === "Мои" ? "mine" : "team";
  const figures = payoutFigures(row);

  useEffect(() => {
    setTx("");
  }, [row.id]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      onChanged();
    } catch (error) {
      toast.error(error instanceof PanelApiError ? error.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex flex-col gap-4" data-ops-payout-panel="">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[15px] font-semibold">#{row.id}</span>
        <Badge tone={mode === "incoming" ? "blue" : mode === "mine" ? "yellow" : "default"}>
          {mode === "incoming" ? "В ожидании" : mode === "mine" ? "На выплате · обычно до 3 часов" : "У другого оператора"}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-2 text-[13px]">
        <Mini label="Списано ₽" value={money(figures.amount)} mono />
        <Mini label="Комиссия ₽" value={money(figures.fee)} mono />
        <Mini label="К выплате ₽" value={money(figures.payout)} mono />
        <Mini label="Метод" value={payoutMethodLabel(row)} />
        <Mini
          label="Клиент"
          value={
            <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <OpsClientLink userId={userId} tab="casino">
                {playerName(row)}
              </OpsClientLink>
              {userId != null ? (
                <OpsClientLink
                  userId={userId}
                  tab="casino"
                  className="text-[12px] text-[var(--blue)] underline-offset-2 hover:underline"
                >
                  Профиль →
                </OpsClientLink>
              ) : null}
            </span>
          }
        />
        <Mini label="Баланс, ₽" value={money(player.available_rub)} mono />
        <Mini label="Отыгрыш" value={locked > 0 ? `заперто ${money(locked)} ₽` : "открыт"} />
        <Mini
          label="Рельс"
          value={
            remainingRail > 0.01
              ? `Сначала карта: ${money(remainingRail)} ₽`
              : cryptoAllowed
                ? "Крипта разрешена"
                : "Сначала карта"
          }
        />
        <Mini label="FocusLucky" value={String(Number(player.raffle_tickets ?? 0))} />
      </div>

      {(player.recent_games ?? []).length > 0 ? (
        <div className="text-[12px] text-[var(--text-muted)]">
          Последние:{" "}
          {(player.recent_games ?? [])
            .slice(0, 3)
            .map((game) => `${String(game.label ?? game.game_type ?? "игра")} ${String(game.result_label ?? "")}`)
            .join(" · ")}
        </div>
      ) : null}

      <CopyField label={isCrypto ? "Адрес кошелька" : "Реквизиты"} value={String(row.requisites ?? "")} />

      <div className="flex flex-col gap-3 border-t border-[var(--border)] pt-4">
        {mode === "team" ? (
          <p className="text-[12px] text-[var(--text-muted)]">В работе у другого оператора</p>
        ) : (
          <>
            {mode === "incoming" ? (
              <Button
                variant="primary"
                disabled={actionDisabled}
                title={!shiftOpen ? "Откройте смену на дашборде" : undefined}
                onClick={() => run(() => claimCasinoPayout(row.id), "Передана на выплату")}
              >
                Передать на выплату
              </Button>
            ) : null}
            {mode === "mine" && isCrypto ? (
              <div className="flex flex-col gap-2">
                <Field label="TX hash выплаты (вставьте)">
                  <Input
                    disabled={!shiftOpen}
                    value={tx}
                    onChange={(event) => setTx(event.target.value)}
                    placeholder="hash транзакции"
                    className="font-mono"
                  />
                </Field>
                <Button
                  variant="primary"
                  disabled={actionDisabled || !tx.trim()}
                  onClick={() => run(() => payoutCasinoWithdrawal(row.id, tx.trim()), "Выплата отмечена")}
                >
                  Подтвердить выплату
                </Button>
              </div>
            ) : null}
            {mode === "mine" && !isCrypto ? (
              <Button
                variant="primary"
                disabled={actionDisabled}
                title={!shiftOpen ? "Откройте смену на дашборде" : undefined}
                onClick={() => run(() => paidCasinoWithdrawal(row.id), "Отмечено оплаченным")}
              >
                Отметить оплаченным
              </Button>
            ) : null}
            <Button
              variant="danger"
              disabled={actionDisabled}
              title={!shiftOpen ? "Откройте смену на дашборде" : undefined}
              onClick={() => run(() => rejectCasinoPayout(row.id), "Отклонено")}
            >
              Отклонить
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}

function Mini({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className={cx("mt-0.5 break-words text-[13px]", mono && "font-mono")}>{value}</div>
    </div>
  );
}
