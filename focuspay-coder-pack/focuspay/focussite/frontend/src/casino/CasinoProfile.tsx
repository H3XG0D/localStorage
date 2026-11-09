import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "@/lib/api";
import {
  getCasinoPlayer,
  getCasinoPlayerHistory,
  getCasinoPlayerHistoryGrouped,
  type CasinoHistoryFairness,
  type CasinoHistoryItem,
  type CasinoHistorySection,
  type CasinoPlayerProfile,
} from "@/lib/public";
import { getBalance, getLedger, getWithdrawals, type BalanceStats } from "@/lib/user";
import { useSession } from "@/lib/session";
import { useCasinoCashier } from "./CasinoCashier";
import {
  currentCommissionHeadline,
  formatRub,
  levelCommissionPair,
  nextLevelCopy,
  nextLevelTurnoverCopy,
} from "./casinoLevelCopy";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CasinoPlayerChip } from "./CasinoPlayerChip";
import {
  availableAfterWagering,
  isDepositLedgerEntry,
  spendableBalanceRub,
  unpackLedgerEntries,
  walletCountLabel,
} from "./casinoWalletRules";
import { CASINO_BALANCE_EVENT } from "./gameCatalog";

function formatDay(iso: string | null): string {
  if (!iso) return "—";
  const [year, month, day] = iso.slice(0, 10).split("-");
  if (!year || !month || !day) return iso;
  return `${day}.${month}.${year}`;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const stamp = new Date(iso);
  if (Number.isNaN(stamp.getTime())) return formatDay(iso);
  return stamp.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function fairnessHref(fairness: CasinoHistoryFairness): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(fairness)) {
    if (value == null || value === "") continue;
    params.set(key, String(value));
  }
  return casinoTo(`/casino/fairness?${params.toString()}`);
}

/** Web-only accounts use negative client_user_id. 0 is the empty-seat sentinel. */
export function parseCasinoPlayerLookup(userId: string | undefined): number | "me" | null {
  if (userId == null || userId === "" || userId === "me") return "me";
  if (!/^-?\d+$/.test(userId)) return null;
  const id = Number(userId);
  if (!Number.isFinite(id) || id === 0) return null;
  return id;
}

/** Own profile lives at /casino/me so negative web ids never hit a /u/0 redirect. */
export function CasinoMeRedirect() {
  return <CasinoProfile />;
}

export function CasinoProfile() {
  const { userId } = useParams();
  const { isAuthed, loading } = useSession();
  const navigate = useNavigate();
  const [data, setData] = useState<CasinoPlayerProfile | null>(null);
  const [error, setError] = useState("");
  const lookup = parseCasinoPlayerLookup(userId);

  useEffect(() => {
    if (loading) return;
    if (!isAuthed) {
      goCasinoLogin(navigate, lookup === "me" || lookup == null ? "/casino/me" : `/casino/u/${lookup}`);
      return;
    }
    if (lookup == null) {
      setData(null);
      setError("Игрок не найден");
      return;
    }
    setError("");
    getCasinoPlayer(lookup)
      .then(setData)
      .catch((err) => {
        setData(null);
        setError(err instanceof ApiError ? err.message : "Не удалось открыть профиль");
      });
  }, [isAuthed, loading, lookup, navigate]);

  return (
    <div className="casino-profile" data-casino-profile={lookup == null ? "" : String(lookup)}>
      <nav className="casino-crumb" aria-label="Навигация">
        <Link to={casinoTo("/casino")}>Лобби</Link>
        <span className="casino-crumb-sep" aria-hidden>
          /
        </span>
        <span>Профиль</span>
      </nav>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {data ? data.is_own ? <OwnCasinoProfile data={data} lookup={lookup === "me" ? "me" : lookup ?? "me"} /> : <PublicCasinoProfile data={data} lookup={lookup ?? data.player.user_id} /> : !error ? (
        <p className="casino-muted">Загрузка профиля…</p>
      ) : null}
    </div>
  );
}

function PublicCasinoProfile({
  data,
  lookup,
}: {
  data: CasinoPlayerProfile;
  lookup: number | "me";
}) {
  return (
    <div className="casino-profile-public" data-casino-public-profile="">
      <header className="casino-profile-head">
        <CasinoPlayerChip actor={data.player} linked={false} size={56} />
        <div>
          <h1>{data.player.display_name}</h1>
          <p className="casino-muted">Уровень {data.level.index}</p>
        </div>
      </header>
      <PublicLevelCard data={data} />
      <PlayerGameHistory lookup={lookup} />
    </div>
  );
}

function OwnCasinoProfile({
  data,
  lookup,
}: {
  data: CasinoPlayerProfile;
  lookup: number | "me";
}) {
  const { openCashier } = useCasinoCashier();
  const [balance, setBalance] = useState<BalanceStats | null>(null);
  const [depositCount, setDepositCount] = useState(0);
  const [withdrawCount, setWithdrawCount] = useState(0);
  const [countsReady, setCountsReady] = useState(false);
  const lockedRub = Number(data.own?.wagering.locked_rub ?? 0);
  const availableRub = availableAfterWagering(
    Number(balance?.available_rub ?? data.own?.available_rub ?? 0),
    lockedRub,
  );

  useEffect(() => {
    function reload() {
      getBalance()
        .then(setBalance)
        .catch(() => undefined);
      Promise.allSettled([getWithdrawals(30, "casino"), getLedger(100)]).then((results) => {
        const [wd, led] = results;
        setWithdrawCount(
          wd.status === "fulfilled" && Array.isArray(wd.value.withdrawals) ? wd.value.withdrawals.length : 0,
        );
        setDepositCount(
          led.status === "fulfilled" ? unpackLedgerEntries(led.value).filter(isDepositLedgerEntry).length : 0,
        );
        setCountsReady(true);
      });
    }
    reload();
    window.addEventListener(CASINO_BALANCE_EVENT, reload);
    return () => window.removeEventListener(CASINO_BALANCE_EVENT, reload);
  }, []);

  return (
    <div className="casino-profile-own" data-casino-own-profile="">
      <header className="casino-profile-head">
        <CasinoPlayerChip actor={data.player} linked={false} size={56} />
        <div className="casino-profile-head-copy">
          <h1>Привет, {data.player.display_name}</h1>
          <p className="casino-muted">Уровень, оборот и комиссия</p>
        </div>
        <div className="casino-profile-cashier">
          <button type="button" className="casino-btn casino-profile-deposit" onClick={() => openCashier("deposit")}>
            Пополнить
          </button>
          <button type="button" className="casino-btn casino-btn-ghost" onClick={() => openCashier("withdraw")}>
            Вывести
          </button>
        </div>
      </header>
      <LevelProgressCard data={data} includeBonus />
      <div className="casino-stat-grid">
        <StatTile label="Баланс, ₽" value={formatRub(spendableBalanceRub(balance ?? data.own))} />
        <StatTile label="Доступно к выводу, ₽" value={formatRub(availableRub)} />
        <StatTile label="Всего поставлено, ₽" value={formatRub(data.lifetime_wager_rub)} />
        <StatTile label="Операций" value={walletCountLabel(countsReady, depositCount + withdrawCount)} />
      </div>
      <p className="casino-muted">
        <Link to={casinoTo("/casino/wallet")}>Кошелёк — история пополнений и выводов</Link>
      </p>
      <WeekByGame data={data} />
      <PlayerGameHistory lookup={lookup} />
      <nav className="casino-profile-links" aria-label="Разделы профиля">
        <Link to={casinoTo("/casino/settings")}>Настройки профиля</Link>
        <Link to={casinoTo("/casino/fairness")}>Проверка честности</Link>
      </nav>
    </div>
  );
}

function PublicLevelCard({ data }: { data: CasinoPlayerProfile }) {
  const progress = levelProgress(data);
  return (
    <section className="casino-level-card" data-casino-level-card="public">
      <div className="casino-level-card-head">
        <span className="casino-level-badge">Уровень {data.level.index}</span>
        <span className="casino-muted">Всего поставлено {formatRub(data.lifetime_wager_rub)}</span>
      </div>
      <div className="casino-level-bar" aria-hidden>
        <span style={{ width: `${progress}%` }} />
      </div>
      <p data-casino-next-level="">{nextLevelTurnoverCopy(data)}</p>
    </section>
  );
}

function LevelProgressCard({
  data,
  includeBonus,
}: {
  data: CasinoPlayerProfile;
  includeBonus: boolean;
}) {
  const progress = levelProgress(data);
  const remainingRaw = data.own
    ? Number(data.own.wagering.remaining_house_take_rub ?? data.own.wagering.remaining_rub ?? 0)
    : NaN;
  const remainingWagering = Number.isFinite(remainingRaw) && remainingRaw > 0 ? formatRub(remainingRaw) : null;
  return (
    <section className="casino-level-card" data-casino-level-card="">
      <div className="casino-level-card-head">
        <span className="casino-level-badge">Уровень {data.level.index}</span>
        <span className="casino-muted">Оборот недели {formatRub(data.wager_rub)}</span>
      </div>
      <div className="casino-level-bar" aria-hidden>
        <span style={{ width: `${progress}%` }} />
      </div>
      <p data-casino-commission="">{currentCommissionHeadline(data)}</p>
      <p className="casino-muted">{levelCommissionPair(data.level)}</p>
      {remainingWagering ? <p className="casino-muted">Отыгрыш {remainingWagering}</p> : null}
      <p data-casino-next-level="">{nextLevelCopy(data, { includeBonus })}</p>
    </section>
  );
}

function WeekByGame({ data }: { data: CasinoPlayerProfile }) {
  return (
    <section className="casino-section">
      <h2 className="casino-section-title">Неделя по играм</h2>
      {data.wager_by_game.length === 0 ? (
        <p className="casino-muted">Пока без ставок на этой неделе.</p>
      ) : (
        <ul className="casino-profile-games">
          {data.wager_by_game.map((row) => (
            <li key={row.game_type}>
              <span>{row.label}</span>
              <strong>{formatRub(row.wager_rub)}</strong>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PlayerGameHistory({ lookup }: { lookup: number | "me" }) {
  const [sections, setSections] = useState<CasinoHistorySection[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [moreBusy, setMoreBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    getCasinoPlayerHistoryGrouped(lookup)
      .then((payload) => {
        if (cancelled) return;
        setSections(payload.sections);
      })
      .catch((err) => {
        if (cancelled) return;
        setSections([]);
        setError(err instanceof ApiError ? err.message : "Не удалось загрузить игры");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [lookup]);

  async function loadMore(gameType: string, before: string) {
    if (moreBusy) return;
    setMoreBusy(gameType);
    try {
      const payload = await getCasinoPlayerHistory(lookup, {
        game_type: gameType,
        limit: 5,
        before,
      });
      setSections((current) =>
        current.map((section) =>
          section.game_type === gameType
            ? {
                ...section,
                items: [...section.items, ...payload.items],
                next_before: payload.next_before,
              }
            : section,
        ),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить игры");
    } finally {
      setMoreBusy(null);
    }
  }

  return (
    <section className="casino-section" data-casino-game-history="">
      <h2 className="casino-section-title">История игр</h2>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {loading ? <p className="casino-muted">Загрузка игр…</p> : null}
      {!loading && sections.length === 0 && !error ? (
        <p className="casino-muted">Пока нет сыгранных раундов.</p>
      ) : null}
      <div className="casino-profile-history-grid">
        {sections.map((section) => (
          <div
            key={section.game_type}
            className="casino-profile-history-game"
            data-casino-history-game={section.game_type}
          >
            <h3 className="casino-profile-history-game-title">{section.label}</h3>
            <ul className="casino-profile-history">
              {section.items.map((row) => (
                <HistoryRow key={`${row.game_type}:${row.round_id}:${row.settled_at}`} row={row} />
              ))}
            </ul>
            {section.next_before ? (
              <button
                type="button"
                className="casino-btn casino-btn-ghost casino-profile-history-more"
                onClick={() => void loadMore(section.game_type, section.next_before as string)}
                disabled={moreBusy === section.game_type}
              >
                {moreBusy === section.game_type ? "Загрузка…" : "Посмотреть больше"}
              </button>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function HistoryRow({ row }: { row: CasinoHistoryItem }) {
  const stake =
    row.tickets != null && Number(row.stake_rub ?? 0) <= 0
      ? `${row.tickets} билетов`
      : row.stake_rub
        ? formatRub(row.stake_rub)
        : "—";
  return (
    <li className="casino-profile-history-row" data-casino-history-result={row.result}>
      <div className="casino-profile-history-main">
        <strong>{row.label}</strong>
        <span className={`casino-profile-history-result is-${row.result}`}>{row.result_label}</span>
      </div>
      <p className="casino-muted">
        {row.share_percent ? `${Number(row.share_percent).toFixed(1)}% · ` : null}
        ставка {stake}
        {row.settled_at ? ` · ${formatWhen(row.settled_at)}` : null}
      </p>
      <div className="casino-profile-history-actions">
        <Link to={casinoTo(row.href)} className="casino-btn casino-btn-ghost">
          Открыть
        </Link>
        {row.fairness ? (
          <Link to={fairnessHref(row.fairness)} className="casino-btn casino-btn-ghost">
            Проверить
          </Link>
        ) : null}
      </div>
    </li>
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

function levelProgress(data: CasinoPlayerProfile): number {
  const current = Number(data.wager_rub);
  const nextMin = Number(data.next_level?.min_wager_rub);
  const floor = Number(data.level.min_wager_rub);
  if (!Number.isFinite(current)) return 0;
  if (!Number.isFinite(nextMin) || nextMin <= floor) return 100;
  return Math.max(0, Math.min(100, ((current - floor) / (nextMin - floor)) * 100));
}
