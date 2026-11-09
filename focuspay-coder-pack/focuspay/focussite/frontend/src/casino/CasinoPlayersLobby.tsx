import { useEffect, useMemo, useRef, useState } from "react";
import { Plus, RefreshCw, SlidersHorizontal, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import {
  addCasinoV2Bot,
  cancelCasinoV2Table,
  chooseCasinoV2Draw,
  createCasinoV2Table,
  getCasinoV2Table,
  getCasinoDuels,
  getCasinoV2Tables,
  hitCasinoV2Table,
  joinCasinoDuel,
  joinCasinoV2Table,
  leaveCasinoV2Table,
  rollCasinoV2Table,
  standCasinoV2Table,
  startCasinoV2Table,
  type CasinoDuelCard,
  type CasinoV2TableView,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo } from "./casinoPaths";
import { prefersCasinoReducedMotion } from "./CasinoDice";
import { CasinoPlayerChip } from "./CasinoPlayerChip";
import { CasinoStartCountdown } from "./CasinoStartCountdown";
import { CasinoRoundResult } from "./CasinoRoundResult";
import { CasinoV2CompactPlay, v2StatusLabel } from "./CasinoV2CompactPlay";
import { goCasinoLogin } from "./casinoPaths";
import { CASINO_BALANCE_EVENT } from "./gameCatalog";
import { useWalletScopeRefresh } from "./walletScope";
import { gameRailIcon } from "./gameRailIcon";
import { mergeV2LobbyTables } from "./v2LobbyMerge";
import { v2MyRoundResult, v2ReplayBody } from "./v2RoundResult";
import { useBaccaratStreets } from "./useBaccaratStreets";
import { useV2RoundNotice } from "./useV2RoundNotice";

const RESULT_HOLD_MS = 6000;
const STAKE_CHIPS = [10, 25, 50, 100, 250, 500];
const SEAT_CHOICES = [2, 3, 4, 5, 6];
const V2_TABLE_GAMES = new Set(["pvp_dice", "baccara", "blackjack"]);
export type StakeSortDir = "asc" | "desc";

function formatRub(value: number | string): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) || 0)} ₽`;
}

function previewPot(stake: number, seats: number): { pot: number; commission: number; net: number } {
  const pot = Math.round(stake * seats * 100) / 100;
  const commission = Math.round(pot * 0.05 * 100) / 100;
  return { pot, commission, net: Math.round((pot - commission) * 100) / 100 };
}

function gameHint(gameType: string, preview: { pot: number; commission: number; net: number }): string {
  const money = `Равные ставки. Банк ${formatRub(preview.pot)} · комиссия ${formatRub(preview.commission)} · победителю ${formatRub(preview.net)}.`;
  const sit = "Сесть справа или плюс на место. Когда стол полный — кубик или карты в этой же строке.";
  if (gameType === "blackjack") {
    return `${money} Чужие карты закрыты до итога. Добор или оставить — у себя на столе. Выше без перебора забирает банк. ${sit}`;
  }
  if (gameType === "baccara") {
    return `${money} Ближе к девяти. Пустое место — «+ бот».`;
  }
  return `${money} ${sit}`;
}

function errMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : fallback;
}

function validMaxBet(raw: string): boolean {
  if (!/^\d+$/.test(raw)) return false;
  const value = Number(raw);
  return Number.isInteger(value) && value >= 10 && value <= 100000;
}

function useCompactLobby(): boolean {
  const [compact, setCompact] = useState(() => window.matchMedia("(max-width: 820px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 820px)");
    const change = () => setCompact(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  return compact;
}

function lobbyTitle(gameType: string): string {
  if (gameType === "baccara") return "Баккара";
  if (gameType === "blackjack") return "Блэкджек";
  return "Кубики";
}

export function CasinoPlayersLobby({
  gameType,
  stakeRub,
  onStakeChange,
}: {
  gameType: string;
  stakeRub: number;
  onStakeChange?: (value: string) => void;
}) {
  const { isAuthed } = useSession();
  const navigate = useNavigate();
  const [tables, setTables] = useState<CasinoV2TableView[]>([]);
  const [duels, setDuels] = useState<CasinoDuelCard[]>([]);
  const [error, setError] = useState("");
  const [busyIds, setBusyIds] = useState<Record<string, boolean>>({});
  const [rollingSeat, setRollingSeat] = useState<{ tableId: string; seat: number | null } | null>(null);
  const [createBusy, setCreateBusy] = useState(false);
  const [maxSeats, setMaxSeats] = useState(4);
  const [sortDir, setSortDir] = useState<StakeSortDir>("asc");
  const [maxBet, setMaxBet] = useState<number | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const [sheet, setSheet] = useState<null | "create" | "filter">(null);
  const [draftMax, setDraftMax] = useState("");
  const compact = useCompactLobby();
  const gameTypeRef = useRef(gameType);
  const dismissedIds = useRef(new Set<string>());
  gameTypeRef.current = gameType;
  const isV2Table = V2_TABLE_GAMES.has(gameType);
  const stake = stakeRub > 0 ? stakeRub : 50;
  const preview = previewPot(stake, maxSeats);
  const ordered = useMemo(
    () =>
      [...tables]
        .sort((a, b) =>
          sortDir === "asc" ? Number(a.stake_rub) - Number(b.stake_rub) : Number(b.stake_rub) - Number(a.stake_rub),
        )
        .sort((a, b) => Number(b.is_seated) - Number(a.is_seated)),
    [tables, sortDir],
  );
  const orderedDuels = useMemo(
    () => [...duels].sort((a, b) => sortDir === "asc" ? a.bet_rub - b.bet_rub : b.bet_rub - a.bet_rub),
    [duels, sortDir],
  );
  const visibleTables = useMemo(
    () => ordered.filter((row) => maxBet == null || Number(row.stake_rub) <= maxBet),
    [ordered, maxBet],
  );
  const visibleDuels = useMemo(
    () => orderedDuels.filter((row) => maxBet == null || row.bet_rub <= maxBet),
    [orderedDuels, maxBet],
  );
  const draftInvalid = draftMax !== "" && !validMaxBet(draftMax);
  const seatedIds = useMemo(
    () => tables.filter((row) => row.is_seated).map((row) => row.table_id),
    [tables],
  );

  function applyTable(next: CasinoV2TableView) {
    if (dismissedIds.current.has(next.table_id)) return;
    setTables((prev) => {
      const index = prev.findIndex((row) => row.table_id === next.table_id);
      if (index < 0) return [next, ...prev];
      const copy = prev.slice();
      copy[index] = next;
      return copy;
    });
  }

  async function load() {
    const requested = gameType;
    setError("");
    if (!isV2Table) return;
    try {
      const [payload, duelPayload] = await Promise.all([getCasinoV2Tables(requested), getCasinoDuels()]);
      if (gameTypeRef.current !== requested) return;
      setDuels(duelPayload.groups.flatMap((group) => group.duels).filter((duel) => duel.game_type === requested));
      setTables((prev) =>
        mergeV2LobbyTables(payload.tables || [], prev, requested).filter(
          (row) => !dismissedIds.current.has(row.table_id),
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось обновить лобби");
    }
  }

  useEffect(() => {
    dismissedIds.current = new Set();
    setTables([]);
    setDuels([]);
    void load();
  }, [gameType]);

  useWalletScopeRefresh(() => {
    dismissedIds.current = new Set();
    setTables([]);
    setDuels([]);
    void load();
  });

  useEffect(() => {
    if (!isV2Table) return;
    const poll = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(poll);
  }, [gameType, isV2Table]);

  useEffect(() => {
    if (!seatedIds.length) return;
    const poll = window.setInterval(() => {
      void Promise.all(
        seatedIds.map(async (tableId) => {
          try {
            applyTable(await getCasinoV2Table(tableId));
          } catch {
            /* keep */
          }
        }),
      );
    }, 1000);
    return () => window.clearInterval(poll);
  }, [seatedIds.join(",")]);

  function needLogin() {
    goCasinoLogin(navigate, `/casino/play/${gameType}?mode=players`);
  }

  async function runTable(tableId: string, fn: () => Promise<void>) {
    setBusyIds((current) => ({ ...current, [tableId]: true }));
    try {
      await fn();
    } finally {
      setBusyIds((current) => {
        const next = { ...current };
        delete next[tableId];
        return next;
      });
    }
  }

  async function onCreate() {
    if (!isAuthed) {
      needLogin();
      return;
    }
    setCreateBusy(true);
    try {
      const created = await createCasinoV2Table({
        game_type: gameType,
        stake_rub: stake,
        max_seats: maxSeats,
        bot_count: 0,
        autojoin: false,
      });
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      if (created.table) applyTable(created.table);
      else await load();
      setSheet(null);
    } catch (err) {
      toast.error(errMessage(err, "Не удалось открыть стол"));
    } finally {
      setCreateBusy(false);
    }
  }

  async function onJoinDuel(duel: CasinoDuelCard) {
    if (!isAuthed) {
      needLogin();
      return;
    }
    await runTable(duel.game_id, async () => {
      try {
        const result = await joinCasinoDuel(duel.game_id);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        navigate(casinoTo(`/casino/duels/${result.game_id}`));
      } catch (err) {
        toast.error(errMessage(err, "Не удалось войти в игру"));
        void load();
      }
    });
  }

  async function onJoinV2(row: CasinoV2TableView) {
    if (!isAuthed) {
      needLogin();
      return;
    }
    if (row.is_seated) {
      await load();
      return;
    }
    await runTable(row.table_id, async () => {
      try {
        const result = await joinCasinoV2Table(row.table_id, row.state_version);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        if (result.table) applyTable(result.table);
        await load();
      } catch (err) {
        toast.error(errMessage(err, "Не удалось войти"));
        void load();
      }
    });
  }

  async function onLeaveV2(row: CasinoV2TableView) {
    if (!isAuthed) {
      needLogin();
      return;
    }
    await runTable(row.table_id, async () => {
      try {
        const fresh = await getCasinoV2Table(row.table_id);
        if (fresh.can_cancel) await cancelCasinoV2Table(fresh.table_id, fresh.state_version);
        else await leaveCasinoV2Table(fresh.table_id, fresh.state_version);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        toast.success(fresh.can_cancel ? "Стол отменён" : "Вы встали со стола");
        await load();
      } catch (err) {
        toast.error(errMessage(err, "Не удалось выйти"));
        void load();
      }
    });
  }

  async function onAddBotV2(row: CasinoV2TableView) {
    if (!isAuthed) {
      needLogin();
      return;
    }
    await runTable(row.table_id, async () => {
      try {
        const fresh = await getCasinoV2Table(row.table_id);
        const result = await addCasinoV2Bot(fresh.table_id, fresh.state_version);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        applyTable(result.table);
        await load();
      } catch (err) {
        toast.error(errMessage(err, "Не удалось посадить бота"));
        void load();
      }
    });
  }

  async function withFresh(
    row: CasinoV2TableView,
    action: (fresh: CasinoV2TableView) => Promise<{ table: CasinoV2TableView }>,
    fail: string,
  ) {
    if (!isAuthed) {
      needLogin();
      return;
    }
    await runTable(row.table_id, async () => {
      try {
        const fresh = await getCasinoV2Table(row.table_id);
        const result = await action(fresh);
        applyTable(result.table);
      } catch (err) {
        toast.error(errMessage(err, fail));
        void load();
      }
    });
  }

  async function onStart(row: CasinoV2TableView) {
    await withFresh(row, (fresh) => startCasinoV2Table(fresh.table_id, fresh.state_version), "Не удалось начать");
  }

  async function onRoll(row: CasinoV2TableView) {
    setRollingSeat({ tableId: row.table_id, seat: row.my_seat_no });
    await withFresh(row, (fresh) => rollCasinoV2Table(fresh.table_id, fresh.state_version), "Не удалось кинуть кубик");
    window.setTimeout(() => setRollingSeat(null), prefersCasinoReducedMotion() ? 0 : 700);
  }

  async function onDraw(row: CasinoV2TableView, choice: "tie_split" | "redeal" = "tie_split") {
    await withFresh(
      row,
      (fresh) => chooseCasinoV2Draw(fresh.table_id, fresh.state_version, choice),
      choice === "redeal" ? "Не удалось перераздать" : "Не удалось разделить банк",
    );
  }

  function onReplay(row: CasinoV2TableView) {
    const next = v2ReplayBody(row);
    dismissedIds.current.add(row.table_id);
    onStakeChange?.(String(next.stake_rub));
    setMaxSeats(next.max_seats);
    setTables((prev) => prev.filter((item) => item.table_id !== row.table_id));
  }

  async function onHit(row: CasinoV2TableView) {
    await withFresh(row, (fresh) => hitCasinoV2Table(fresh.table_id, fresh.state_version), "Не удалось добрать");
  }

  async function onStand(row: CasinoV2TableView) {
    await withFresh(row, (fresh) => standCasinoV2Table(fresh.table_id, fresh.state_version), "Не удалось оставить");
  }

  if (!isV2Table) {
    return (
      <div className="casino-players-lobby" data-casino-players-lobby={gameType}>
        <p className="casino-muted">Эта игра открывается как стол 2–6 с игроками.</p>
      </div>
    );
  }

  const barBusy = createBusy || Object.keys(busyIds).length > 0;
  void barBusy;
  const stakeValid = Number.isInteger(stake) && stake >= 10 && stake <= 100000;

  useEffect(() => {
    if (!sheet) return;
    const back = (event: Event) => {
      event.preventDefault();
      setSheet(null);
    };
    window.addEventListener("focusbet:back", back);
    return () => window.removeEventListener("focusbet:back", back);
  }, [sheet]);

  const createFields = (
    <>
        <div className="casino-create-card-head">
          <div>
            <p className="casino-create-eyebrow">{lobbyTitle(gameType)}</p>
            <h2>Новый стол</h2>
            <p className="casino-muted">Ставка за место и число игроков. Пустые места можно закрыть ботом.</p>
          </div>
          {compact ? null : (
            <button type="button" className="casino-icon-btn casino-create-refresh" onClick={() => void load()} aria-label="Обновить">
              <RefreshCw size={17} />
            </button>
          )}
        </div>
        <div className="casino-create-grid">
          <div className="casino-create-field">
            <span>Ставка за место, ₽</span>
            <div className="casino-amount-control">
              <input
                type="text"
                inputMode="decimal"
                value={Number.isFinite(stakeRub) && stakeRub > 0 ? String(stakeRub) : ""}
                onChange={(event) => onStakeChange?.(event.target.value)}
                aria-label="Сумма ставки"
                aria-invalid={!stakeValid}
                aria-describedby="casino-create-bet-help"
              />
              <strong>₽</strong>
            </div>
            <p id="casino-create-bet-help" className={stakeValid ? "casino-field-hint" : "casino-field-error"}>
              {stakeValid ? "От 10 до 100 000 ₽, целое число" : "Введите целую сумму от 10 до 100 000 ₽"}
            </p>
          </div>
          <div className="casino-create-field">
            <span>Количество игроков</span>
            <div className="casino-seat-picker" data-casino-v2-seats-pick="">
              {SEAT_CHOICES.map((count) => (
                <button
                  key={count}
                  type="button"
                  className={maxSeats === count ? "is-on" : ""}
                  aria-pressed={maxSeats === count}
                  onClick={() => setMaxSeats(count)}
                >
                  {count}
                </button>
              ))}
            </div>
          </div>
          <div className="casino-create-field casino-create-field-wide">
            <span>Быстрый выбор</span>
            <div className="casino-choice-row">
              {STAKE_CHIPS.map((amount) => (
                <button
                  key={amount}
                  type="button"
                  className={stakeRub === amount ? "is-on" : ""}
                  aria-pressed={stakeRub === amount}
                  onClick={() => onStakeChange?.(String(amount))}
                >
                  {formatRub(amount)}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="casino-create-summary">
          <div><span>Игроков</span><strong>{maxSeats}</strong></div>
          <div><span>Банк при полном столе</span><strong>{formatRub(preview.pot)}</strong></div>
        </div>
        <button type="button" className="casino-btn casino-btn-primary casino-create-submit" disabled={createBusy || !stakeValid} onClick={() => void onCreate()}>
          Создать стол{stakeValid ? ` · ${formatRub(stake)}` : ""}
        </button>
    </>
  );

  return (
    <div className="casino-players-lobby" data-casino-players-lobby={gameType}>
      <header className="casino-lobby-game-head">
        <span className="casino-lobby-game-icon" aria-hidden>{gameRailIcon(gameType, "")}</span>
        <div>
          <h2>{lobbyTitle(gameType)}</h2>
          <p>{lobbyTitle(gameType)} · общий стол</p>
        </div>
        <span className="casino-lobby-open-pill">Лобби открыто</span>
      </header>
      {compact ? null : (
      <section className="casino-create-card casino-create-card-table" data-casino-table-create="">
        {createFields}
      </section>
      )}
      <div className="casino-lobby-tables">
      <div className="casino-table-toolbar">
        <h2>Открытые столы <span>{visibleTables.length + visibleDuels.length}</span></h2>
        <button
          type="button"
          className={`casino-btn casino-btn-ghost casino-stake-sort${sortDir === "desc" ? " is-desc" : ""}`}
          data-casino-stake-sort=""
          aria-pressed={sortDir === "desc"}
          onClick={() => setSortDir((dir) => (dir === "asc" ? "desc" : "asc"))}
        >
          {sortDir === "asc" ? "Низкие" : "Высокие"}
        </button>
        <button
          type="button"
          className="casino-btn casino-btn-ghost casino-table-filter"
          data-casino-table-filter=""
          aria-expanded={compact ? sheet === "filter" : filterOpen}
          onClick={() => {
            setDraftMax(maxBet == null ? "" : String(maxBet));
            if (compact) setSheet("filter");
            else setFilterOpen((open) => !open);
          }}
        >
          <SlidersHorizontal size={16} aria-hidden /> Фильтры
          {maxBet != null ? <i className="casino-filter-dot" /> : null}
        </button>
      </div>
      {maxBet != null ? (
        <button type="button" className="casino-btn casino-btn-ghost casino-active-filter" data-casino-max-bet={maxBet} onClick={() => setMaxBet(null)}>
          До {formatRub(maxBet)} · сбросить
        </button>
      ) : null}
      {filterOpen ? (
        <form
          className="casino-table-filter-panel"
          data-casino-table-filter-panel=""
          onSubmit={(event) => {
            event.preventDefault();
            if (draftInvalid) return;
            setMaxBet(draftMax === "" ? null : Number(draftMax));
            setFilterOpen(false);
          }}
        >
          <label className="casino-field">
            Максимальная ставка, ₽
            <input
              name="maximum-stake"
              inputMode="numeric"
              maxLength={6}
              autoComplete="off"
              value={draftMax}
              aria-invalid={draftInvalid}
              aria-describedby="casino-filter-help"
              placeholder="Без ограничений"
              onChange={(event) => setDraftMax(event.target.value.replace(/\D/g, "").slice(0, 6))}
            />
          </label>
          <p id="casino-filter-help" className={draftInvalid ? "casino-duel-error" : "casino-muted"}>
            {draftInvalid ? "Введите целую сумму от 10 до 100 000 ₽ или очистите поле." : "От 10 до 100 000 ₽. Пустое поле показывает все столы."}
          </p>
          <div className="casino-create-actions-line">
            <button type="button" className="casino-btn casino-btn-ghost" onClick={() => setDraftMax("")}>Сбросить</button>
            <button type="submit" className="casino-btn casino-btn-primary" disabled={draftInvalid}>Применить</button>
          </div>
        </form>
      ) : null}
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {visibleDuels.length > 0 ? (
        <div className="casino-room-list casino-legacy-duel-list" data-casino-legacy-duels="">
          {visibleDuels.map((duel) => (
            <article key={duel.game_id} className="casino-room-row casino-room-row-legacy">
              <div className="casino-room-row-avatars">
                <CasinoPlayerChip actor={duel.creator ?? null} size={48} />
                <span className="casino-duel-vs-mark">vs</span>
                <CasinoPlayerChip actor={duel.opponent ?? null} empty={!duel.opponent_occupied} size={48} />
              </div>
              <div className="casino-room-row-bid">
                <button type="button" className="casino-room-row-sit" disabled={Boolean(busyIds[duel.game_id]) || duel.opponent_occupied} onClick={() => void onJoinDuel(duel)}>
                  {duel.opponent_occupied ? "Игра началась" : `Войти · ${formatRub(duel.bet_rub)}`}
                </button>
                <span className="casino-room-row-meta">Дуэль 1×1</span>
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {visibleTables.length > 0 ? (
        <div className="casino-room-list" data-casino-v2-lobby="">
          {visibleTables.map((row) => (
            <V2LobbyRow
              key={row.table_id}
              table={row}
              busy={Boolean(busyIds[row.table_id])}
              rollingSeat={rollingSeat?.tableId === row.table_id ? rollingSeat.seat : null}
              onJoin={() => void onJoinV2(row)}
              onLeave={() => void onLeaveV2(row)}
              onAddBot={() => void onAddBotV2(row)}
              onStart={() => void onStart(row)}
              onRoll={() => void onRoll(row)}
              onDraw={(choice) => void onDraw(row, choice)}
              onReplay={() => onReplay(row)}
              replayBusy={createBusy}
              onHit={() => void onHit(row)}
              onStand={() => void onStand(row)}
            />
          ))}
        </div>
      ) : null}
      {visibleTables.length === 0 && visibleDuels.length === 0 ? (
        <div className="casino-lobby-empty">
          {tables.length + duels.length > 0 ? (
            <>
              <h3>Нет подходящих столов</h3>
              <p>Попробуйте увеличить максимальную ставку или сбросить фильтр.</p>
              <button type="button" className="casino-btn casino-btn-ghost" onClick={() => setMaxBet(null)}>Сбросить фильтры</button>
            </>
          ) : (
            <>
              <h3>Первый стол — ваш</h3>
              <p>Выберите ставку и от 2 до 6 мест. Остальные места можно закрыть ботом.</p>
            </>
          )}
        </div>
      ) : null}
      <p className="casino-lobby-info">{gameHint(gameType, preview)}</p>
      </div>
      {compact ? (
        <div className="casino-lobby-bottom-action">
          <button type="button" className="casino-btn casino-btn-primary" onClick={() => setSheet("create")}>
            <Plus size={18} aria-hidden /> Создать стол
          </button>
        </div>
      ) : null}
      {compact && sheet ? (
        <div className="casino-app-sheet-root" data-casino-app-sheet="">
          <button type="button" className="casino-app-sheet-backdrop" aria-label="Закрыть панель" onClick={() => setSheet(null)} />
          <section className="casino-app-sheet" role="dialog" aria-modal="true" aria-label={sheet === "create" ? "Новый стол" : "Фильтры столов"}>
            <header className="casino-app-sheet-head">
              <h2>{sheet === "create" ? "Новый стол" : "Фильтры столов"}</h2>
              <button type="button" className="casino-app-sheet-close" aria-label="Закрыть" onClick={() => setSheet(null)}>
                <X size={18} />
              </button>
            </header>
            {sheet === "create" ? createFields : (
              <form
                className="casino-table-filter-panel"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (draftInvalid) return;
                  setMaxBet(draftMax === "" ? null : Number(draftMax));
                  setSheet(null);
                }}
              >
                <label className="casino-field">
                  Максимальная ставка, ₽
                  <input
                    name="maximum-stake"
                    inputMode="numeric"
                    maxLength={6}
                    autoComplete="off"
                    value={draftMax}
                    aria-invalid={draftInvalid}
                    placeholder="Без ограничений"
                    onChange={(event) => setDraftMax(event.target.value.replace(/\D/g, "").slice(0, 6))}
                  />
                </label>
                <p className={draftInvalid ? "casino-field-error" : "casino-field-hint"}>
                  {draftInvalid ? "Введите целую сумму от 10 до 100 000 ₽ или очистите поле." : "От 10 до 100 000 ₽. Пустое поле показывает все столы."}
                </p>
                <div className="casino-app-sheet-actions">
                  <button type="button" className="casino-btn casino-btn-ghost" onClick={() => setDraftMax("")}>Сбросить</button>
                  <button type="submit" className="casino-btn casino-btn-primary" disabled={draftInvalid}>Применить</button>
                </div>
              </form>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}

function V2LobbyRow({
  table,
  busy,
  rollingSeat,
  onJoin,
  onLeave,
  onAddBot,
  onStart,
  onRoll,
  onDraw,
  onHit,
  onStand,
  onReplay,
  replayBusy,
}: {
  table: CasinoV2TableView;
  busy?: boolean;
  rollingSeat?: number | null;
  onJoin: () => void;
  onLeave: () => void;
  onAddBot: () => void;
  onStart: () => void;
  onRoll: () => void;
  onDraw: (choice: "tie_split" | "redeal") => void;
  onHit: () => void;
  onStand: () => void;
  onReplay: () => void;
  replayBusy?: boolean;
}) {
  const [opened, setOpened] = useState(false);
  const streets = useBaccaratStreets(table);
  useV2RoundNotice(table);
  const replayRef = useRef(onReplay);
  replayRef.current = onReplay;
  const resultHoldId = table.status === "finished" && table.is_seated ? table.table_id : "";
  useEffect(() => {
    if (!resultHoldId) return;
    const timer = window.setTimeout(() => replayRef.current(), RESULT_HOLD_MS);
    return () => window.clearTimeout(timer);
  }, [resultHoldId]);
  const joinable = table.status === "open" && table.free_seats.length > 0 && !table.is_seated;
  const canDrop = Boolean(table.can_cancel || table.can_leave);
  const counting = Boolean(table.countdown_ends_at && (table.status === "open" || table.status === "ready"));
  const finished = table.status === "finished";
  const myResult = v2MyRoundResult(table);
  const playing =
    table.status === "running" ||
    table.status === "tie_break_running" ||
    finished ||
    table.game_state.phase === "draw_choice" ||
    table.game_state.phase === "hitting";
  const expanded = opened || counting || playing || table.is_seated;
  const canAddBot = Boolean(table.can_add_bot && table.is_seated);
  const showHitActions = Boolean((table.can_hit || table.can_stand) && streets.showOutcome && !finished);
  const showDrawChoice = Boolean(table.can_choose_draw && streets.showOutcome && !finished);
  return (
    <article
      className={`casino-room-row is-v2${table.is_seated ? " is-mine" : ""}${expanded ? " is-open" : ""}`}
      data-casino-v2-row={table.table_id}
      onClick={(event) => {
        const target = event.target as HTMLElement | null;
        if (target?.closest("button, a")) return;
        setOpened(true);
      }}
    >
      <div className="casino-room-row-avatars">
        {Array.from({ length: Math.max(2, table.max_seats) }, (_, index) => {
          const seatNo = index + 1;
          const seat = table.roster.find((item) => item.seat_no === seatNo);
          if (seat) {
            const actor = seat.actor ?? null;
            const bot = seat.participant_kind === "bot";
            return (
              <CasinoPlayerChip
                key={`${table.table_id}-${seatNo}`}
                actor={actor}
                size={48}
                linked={Boolean(actor && actor.user_id !== 0 && !bot)}
              />
            );
          }
          if (joinable) {
            return (
              <button key={seatNo} type="button" className="casino-room-join" disabled={busy} aria-label="Сесть" onClick={onJoin}>
                <Plus size={22} strokeWidth={3} />
              </button>
            );
          }
          if (canAddBot) {
            return (
              <button
                key={seatNo}
                type="button"
                className="casino-room-join"
                data-casino-v2-add-bot=""
                disabled={busy}
                aria-label="Добавить бота"
                onClick={onAddBot}
              >
                <Plus size={22} strokeWidth={3} />
              </button>
            );
          }
          return <span key={seatNo} className="casino-room-slot is-empty" />;
        })}
      </div>
      <div className="casino-room-row-bid">
        {joinable ? (
          <button type="button" className="casino-room-row-sit" disabled={busy} onClick={onJoin}>
            Сесть · {formatRub(table.stake_rub)}
          </button>
        ) : (
          <span className="casino-room-row-stake">{formatRub(table.stake_rub)}</span>
        )}
        <span className="casino-room-row-meta">
          {table.roster.length}/{table.max_seats} · {v2StatusLabel(table)}
          {canDrop ? (
            <button type="button" className="casino-room-row-drop" disabled={busy} onClick={onLeave}>
              {table.can_cancel ? "Отменить" : "Встать"}
            </button>
          ) : null}
        </span>
      </div>
      {expanded ? (
        <div className="casino-v2-strip-play">
          <CasinoV2CompactPlay table={table} busy={busy} facesOnly rollingSeat={rollingSeat} onAddBot={canAddBot ? onAddBot : undefined} />
          {table.status === "tie_break_running" ? (
            <p className="casino-muted">Ничья — лидеры кидают ещё раз.</p>
          ) : null}
          {finished && table.is_seated ? (
            <div className="casino-round-result-pop" data-casino-v2-result-pop="">
              <CasinoRoundResult result={myResult} compact>
                <button
                  type="button"
                  className="casino-btn"
                  data-casino-v2-replay=""
                  disabled={replayBusy || busy}
                  onClick={onReplay}
                >
                  К столам
                </button>
              </CasinoRoundResult>
            </div>
          ) : table.is_seated && (table.can_roll || table.can_start || showDrawChoice || showHitActions) ? (
            <div className="casino-v2-strip-actions">
              {showDrawChoice ? (
                <>
                  <button type="button" className="casino-btn" disabled={busy} onClick={() => onDraw("tie_split")}>
                    Разделить банк
                  </button>
                  <button type="button" className="casino-btn casino-btn-ghost" disabled={busy} onClick={() => onDraw("redeal")}>
                    Перераздача
                  </button>
                </>
              ) : showHitActions ? (
                <>
                  {table.can_hit ? (
                    <button type="button" className="casino-btn" disabled={busy} onClick={onHit}>
                      Добрать
                    </button>
                  ) : null}
                  {table.can_stand ? (
                    <button type="button" className="casino-btn casino-btn-ghost" disabled={busy} onClick={onStand}>
                      Оставить
                    </button>
                  ) : null}
                </>
              ) : table.can_roll ? (
                <button type="button" className="casino-btn" disabled={busy} onClick={onRoll}>
                  Кинуть кубик
                </button>
              ) : table.can_start ? (
                <button type="button" className="casino-btn" disabled={busy} onClick={onStart}>
                  Начать
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
      {counting ? <CasinoStartCountdown endsAt={table.countdown_ends_at} /> : null}
    </article>
  );
}
