import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import {
  getCasinoPlayer,
  getCasinoPlayerHistory,
  type CasinoHistoryItem,
  type CasinoPlayerProfile,
} from "@/lib/public";
import {
  cancelWithdrawal,
  getBalance,
  getLedger,
  getWithdrawals,
  type BalanceStats,
  type WithdrawalRow,
} from "@/lib/user";
import { useSession } from "@/lib/session";
import { useCasinoCashier } from "./CasinoCashier";
import { CasinoWithdrawalCard } from "./CasinoWithdrawalCard";
import { formatRub } from "./casinoLevelCopy";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import {
  availableAfterWagering,
  depositLedgerTitle,
  gameResultTone,
  isDepositLedgerEntry,
  spendableBalanceRub,
  unpackLedgerEntries,
  walletCountLabel,
  withdrawalsForHistoryTab,
  type WalletHistoryTab,
  type WalletLedgerLike,
} from "./casinoWalletRules";
import { CASINO_BALANCE_EVENT } from "./gameCatalog";

function formatWhen(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function ledgerAmount(entry: WalletLedgerLike): number {
  const n = Number(entry.amount_rub ?? 0);
  return Number.isFinite(n) ? n : 0;
}

export function CasinoWallet() {
  const { isAuthed, loading } = useSession();
  const navigate = useNavigate();
  const { openCashier } = useCasinoCashier();
  const [data, setData] = useState<CasinoPlayerProfile | null>(null);
  const [balance, setBalance] = useState<BalanceStats | null>(null);
  const [withdrawals, setWithdrawals] = useState<WithdrawalRow[]>([]);
  const [ledger, setLedger] = useState<WalletLedgerLike[]>([]);
  const [games, setGames] = useState<CasinoHistoryItem[]>([]);
  const [error, setError] = useState("");
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  const [historyTab, setHistoryTab] = useState<WalletHistoryTab>("deposit");
  const [countsReady, setCountsReady] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/wallet");
      return;
    }
    setError("");
    function reload() {
      getCasinoPlayer("me")
        .then(setData)
        .catch((err) => {
          setData(null);
          setError(err instanceof ApiError ? err.message : "Не удалось открыть кошелёк");
        });
      getBalance()
        .then(setBalance)
        .catch(() => undefined);
      Promise.allSettled([getWithdrawals(30, "casino"), getLedger(100)]).then((results) => {
        const [wd, led] = results;
        if (wd.status === "fulfilled") {
          setWithdrawals(Array.isArray(wd.value.withdrawals) ? wd.value.withdrawals : []);
        } else {
          setWithdrawals([]);
        }
        if (led.status === "fulfilled") {
          setLedger(unpackLedgerEntries(led.value));
        } else {
          setLedger([]);
        }
        setCountsReady(true);
      });
      getCasinoPlayerHistory("me", { limit: 30 })
        .then((payload) => setGames(Array.isArray(payload.items) ? payload.items : []))
        .catch(() => setGames([]));
    }
    reload();
    window.addEventListener(CASINO_BALANCE_EVENT, reload);
    const poll = window.setInterval(reload, 5000);
    return () => {
      window.clearInterval(poll);
      window.removeEventListener(CASINO_BALANCE_EVENT, reload);
    };
  }, [isAuthed, loading, navigate]);

  const lockedRub = Number(data?.own?.wagering.locked_rub ?? 0);
  const availableRub = availableAfterWagering(
    Number(balance?.available_rub ?? data?.own?.available_rub ?? 0),
    lockedRub,
  );

  const deposits = useMemo(() => ledger.filter(isDepositLedgerEntry), [ledger]);
  const withdrawalRows = useMemo(() => withdrawalsForHistoryTab(withdrawals), [withdrawals]);

  async function onCancel(id: number) {
    if (cancellingId != null) return;
    setCancellingId(id);
    try {
      await cancelWithdrawal(id);
      toast.success("Заявка отменена");
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    } catch (caught) {
      toast.error(caught instanceof ApiError ? caught.message : "Не удалось отменить вывод");
    } finally {
      setCancellingId(null);
    }
  }

  const tabCopy =
    historyTab === "deposit"
      ? { title: "Пополнения", hint: "Зачисления на счёт FocusBet." }
      : historyTab === "withdraw"
        ? { title: "Выводы", hint: "До 5 заявок в работе. Новую — не чаще чем раз в 5 минут. Пока заявка в очереди, её можно отменить." }
        : { title: "Игры", hint: "Сыгранные раунды FocusBet." };

  return (
    <div className="casino-wallet" data-casino-wallet-page="">
      <nav className="casino-crumb" aria-label="Навигация">
        <Link to={casinoTo("/casino")}>Лобби</Link>
        <span className="casino-crumb-sep" aria-hidden>
          /
        </span>
        <span>Кошелёк</span>
      </nav>
      <div>
        <h1>Кошелёк</h1>
        <p className="casino-muted">Пополнения, выводы и история игр FocusBet.</p>
      </div>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      <div className="casino-stat-grid">
        <StatTile label="Пополнения" value={walletCountLabel(countsReady, deposits.length)} />
        <StatTile label="Выводы" value={walletCountLabel(countsReady, withdrawals.length)} />
        <StatTile label="Баланс, ₽" value={formatRub(spendableBalanceRub(balance ?? data?.own))} />
        <StatTile label="Доступно к выводу, ₽" value={formatRub(availableRub)} />
      </div>
      <div className="casino-wallet-actions">
        <button type="button" className="casino-btn" onClick={() => openCashier("deposit")}>
          Пополнить
        </button>
        <button type="button" className="casino-btn casino-btn-ghost" onClick={() => openCashier("withdraw")}>
          Вывести
        </button>
      </div>
      <div className="casino-chip-row" role="tablist" aria-label="История кошелька" data-casino-wallet-tabs="">
        <button
          type="button"
          role="tab"
          aria-selected={historyTab === "deposit"}
          className={historyTab === "deposit" ? "is-on" : ""}
          data-casino-wallet-tab="deposit"
          onClick={() => setHistoryTab("deposit")}
        >
          Пополнения
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={historyTab === "withdraw"}
          className={historyTab === "withdraw" ? "is-on" : ""}
          data-casino-wallet-tab="withdraw"
          onClick={() => setHistoryTab("withdraw")}
        >
          Выводы
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={historyTab === "games"}
          className={historyTab === "games" ? "is-on" : ""}
          data-casino-wallet-tab="games"
          onClick={() => setHistoryTab("games")}
        >
          Игры
        </button>
      </div>
      <section
        className="casino-wallet-card casino-wallet-history"
        data-casino-wallet-history=""
        data-casino-wallet-history-tab={historyTab}
        data-casino-wallet-active={historyTab === "withdraw" ? "" : undefined}
      >
        <h2>{tabCopy.title}</h2>
        <p className="casino-muted">{tabCopy.hint}</p>
        {historyTab === "deposit" ? (
          deposits.length === 0 ? (
            <div className="casino-history-empty">
              <p className="casino-muted">Пока нет пополнений.</p>
              <button type="button" className="casino-btn" onClick={() => openCashier("deposit")}>
                Пополнить
              </button>
            </div>
          ) : (
            <ul className="casino-wallet-history-list">
              {deposits.map((row, index) => {
                const amount = ledgerAmount(row);
                const key = `${String(row.order_id ?? row.note ?? "dep")}:${row.created_at ?? index}`;
                return (
                  <li key={key} className="casino-wallet-history-row" data-casino-wallet-deposit="">
                    <div>
                      <strong>{depositLedgerTitle(row)}</strong>
                      <p className="casino-muted">{formatWhen(row.created_at)}</p>
                      <span className="casino-status-badge" data-casino-status-tone="success">
                        Успешно
                      </span>
                    </div>
                    <span className="casino-mono">
                      {amount >= 0 ? "+" : ""}
                      {formatRub(amount)}
                    </span>
                  </li>
                );
              })}
            </ul>
          )
        ) : null}
        {historyTab === "withdraw" ? (
          withdrawalRows.length === 0 ? (
            <div className="casino-history-empty">
              <p className="casino-muted">Пока нет выводов.</p>
              <button type="button" className="casino-btn" onClick={() => openCashier("withdraw")}>
                Вывести
              </button>
            </div>
          ) : (
            <ul className="casino-wallet-history-list">
              {withdrawalRows.map((row) => (
                <li key={row.id}>
                  <CasinoWithdrawalCard
                    row={row}
                    onCancel={onCancel}
                    cancelling={cancellingId === row.id}
                  />
                </li>
              ))}
            </ul>
          )
        ) : null}
        {historyTab === "games" ? (
          games.length === 0 ? (
            <div className="casino-history-empty">
              <p className="casino-muted">Пока нет сыгранных раундов.</p>
              <Link to={casinoTo("/casino")} className="casino-btn">
                В лобби
              </Link>
            </div>
          ) : (
            <ul className="casino-wallet-history-list">
              {games.map((row) => {
                const stake = Number(row.stake_rub ?? 0);
                return (
                  <li
                    key={`${row.game_type}:${row.round_id}:${row.settled_at}`}
                    className="casino-wallet-history-row"
                    data-casino-wallet-game={row.game_type}
                    data-casino-history-result={row.result}
                  >
                    <div>
                      <strong>{row.label}</strong>
                      <p className="casino-muted">
                        {row.settled_at ? formatWhen(row.settled_at) : ""}
                        {Number.isFinite(stake) && stake > 0 ? ` · ставка ${formatRub(stake)}` : ""}
                      </p>
                      <span className="casino-status-badge" data-casino-status-tone={gameResultTone(row.result)}>
                        {row.result_label}
                      </span>
                    </div>
                    <Link to={casinoTo(row.href)} className="casino-btn casino-btn-ghost">
                      Открыть
                    </Link>
                  </li>
                );
              })}
            </ul>
          )
        ) : null}
      </section>
      <p>
        <Link to={casinoTo("/casino/me")}>Профиль FocusBet</Link>
      </p>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="casino-stat-tile">
      <p>{label}</p>
      <strong>{value}</strong>
    </div>
  );
}
