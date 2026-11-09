import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import {
  createCasinoDuel,
  getCasinoDuels,
  joinCasinoDuel,
  type CasinoDuelCard,
  type CasinoDuelsResponse,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CASINO_CATALOG } from "./gameCatalog";import { CasinoDuelMatchRow } from "./CasinoPlayerChip";
import { TelegramMainButton } from "./TelegramMainButton";
import { useWalletScopeRefresh } from "./walletScope";

const MY_DUELS_KEY = "focuspay_casino_my_duels";
const DUEL_GAMES = CASINO_CATALOG.filter((game) => game.id === "pvp_dice" || game.id === "baccara" || game.id === "blackjack");
const STAKE_CHIPS = [10, 25, 50, 100, 250, 500];

function readMine(): string[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(MY_DUELS_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function rememberMine(gameId: string) {
  const next = [gameId, ...readMine().filter((id) => id !== gameId)].slice(0, 20);
  window.localStorage.setItem(MY_DUELS_KEY, JSON.stringify(next));
}

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₽`;
}

export function CasinoDuels() {
  const { isAuthed } = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [data, setData] = useState<CasinoDuelsResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mine, setMine] = useState<string[]>([]);
  const preselect = params.get("game") || "pvp_dice";
  const [gameType, setGameType] = useState(preselect);
  const [stake, setStake] = useState("50");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  async function load() {
    setError("");
    try {
      setData(await getCasinoDuels());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось обновить дуэли");
    }
  }

  useEffect(() => {
    setMine(readMine());
    void load();
  }, []);

  useWalletScopeRefresh(() => void load());

  useEffect(() => {
    if (params.get("game")) setGameType(params.get("game") || "pvp_dice");
  }, [params]);

  const commission = data?.commission_percent ?? 0;
  const stakeNumber = Number(stake.replace(",", ".")) || 0;

  async function onCreate() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/duels");
      return;
    }
    if (!Number.isFinite(stakeNumber) || stakeNumber <= 0) {
      setError("Укажи ставку");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await createCasinoDuel({ game_type: gameType, stake_rub: stakeNumber, autojoin: false });
      rememberMine(result.game_id);
      setMine(readMine());
      navigate(casinoTo(`/casino/duels/${result.game_id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать дуэль");
    } finally {
      setBusy(false);
    }
  }

  const groups = useMemo(() => {
    const stakeMatch = (value: number) => (stakeNumber > 0 ? Number(value) === stakeNumber : true);
    return (data?.groups ?? []).map((group) => ({
      ...group,
      duels: [...group.duels]
        .filter((duel) => stakeMatch(Number(duel.bet_rub)))
        .sort((a, b) =>
          sortDir === "asc" ? Number(a.bet_rub) - Number(b.bet_rub) : Number(b.bet_rub) - Number(a.bet_rub),
        ),
    }));
  }, [data?.groups, stakeNumber, sortDir]);

  async function onJoinRow(duel: CasinoDuelCard) {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/duels");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await joinCasinoDuel(duel.game_id);
      rememberMine(result.game_id);
      setMine(readMine());
      navigate(casinoTo(`/casino/duels/${result.game_id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось войти в дуэль");
    } finally {
      setBusy(false);
    }
  }

  const mainText = !isAuthed ? "Войти" : "";
  const mainClick = () => goCasinoLogin(navigate, "/casino/duels");

  return (
    <div className="casino-duels" data-casino-duels="1">
      <TelegramMainButton text={mainText || "Пополнить"} onClick={mainClick} visible={Boolean(mainText)} />
      <header className="casino-duels-head">
        <div>
          <nav className="casino-crumb" aria-label="Навигация">
            <Link to={casinoTo("/casino")} data-casino-return="">
              Лобби
            </Link>
            <span className="casino-crumb-sep" aria-hidden>
              /
            </span>
            <span>Дуэли</span>
          </nav>
          <h1>Дуэли</h1>
          <p className="casino-muted" data-casino-commission="">
            Комиссия {commission}% · ставка равна у обоих, победитель забирает банк после комиссии
          </p>
        </div>
        <button type="button" className="casino-btn casino-btn-ghost" onClick={() => void load()} aria-label="Обновить">
          <RefreshCw size={16} />
        </button>
      </header>

      <section className="casino-create-card" data-casino-duel-create="">
        <div className="casino-create-card-head">
          <div>
            <p className="casino-create-eyebrow">Новая дуэль</p>
            <h2>Фильтр ставки</h2>
            <p className="casino-muted">Быстрый выбор или своя сумма. Ниже сразу видны подходящие дуэли, своя ставка — для новой дуэли.</p>
          </div>
          <span className="casino-create-step">Фильтр</span>
        </div>
        <div className="casino-create-grid">
          <label className="casino-create-field">
            <span>Игра</span>
            <select value={gameType} onChange={(event) => setGameType(event.target.value)}>
              {DUEL_GAMES.map((game) => (
                <option key={game.id} value={game.id}>
                  {game.emoji} {game.name}
                </option>
              ))}
            </select>
          </label>
          <div className="casino-create-field">
            <span>Ваша ставка</span>
            <div className="casino-amount-control">
              <input value={stake} onChange={(event) => setStake(event.target.value)} inputMode="decimal" aria-label="Ставка" />
              <strong>₽</strong>
            </div>
          </div>
          <div className="casino-create-field casino-create-field-wide">
            <span>Быстрый выбор</span>
            <div className="casino-choice-row">
              {STAKE_CHIPS.map((amount) => (
                <button key={amount} type="button" className={stakeNumber === amount ? "is-on" : ""} onClick={() => setStake(String(amount))}>
                  {formatRub(amount)}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="casino-create-summary">
          <div><span>Банк дуэли</span><strong>{formatRub(stakeNumber * 2)}</strong></div>
          <div><span>Победитель получит</span><strong>{formatRub(stakeNumber * 2 * (1 - commission / 100))}</strong></div>
        </div>
        <div className="casino-create-actions casino-create-actions-line">
          <button
            type="button"
            className={`casino-btn casino-btn-ghost casino-stake-sort${sortDir === "desc" ? " is-desc" : ""}`}
            data-casino-stake-sort=""
            aria-pressed={sortDir === "desc"}
            onClick={() => setSortDir((dir) => (dir === "asc" ? "desc" : "asc"))}
            title={sortDir === "asc" ? "Сейчас от низких к высоким" : "Сейчас от высоких к низким"}
          >
            {sortDir === "asc" ? "Ставка: сначала низкие" : "Ставка: сначала высокие"}
          </button>
          <button type="button" className="casino-btn casino-btn-primary" disabled={busy} onClick={() => void onCreate()}>
            <Plus size={17} /> Создать дуэль · {formatRub(stakeNumber)}
          </button>
        </div>
      </section>

      {error ? <p className="casino-duel-error">{error}</p> : null}

      {groups.map((group) => (
        <section key={group.band} className="casino-section" data-casino-band={group.band}>
          <div className="casino-duels-band">
            <h2 className="casino-section-title">{group.label}</h2>
            <span className="casino-muted">{group.fill_label}</span>
          </div>
          {group.duels.length === 0 ? (
            <p className="casino-muted">Пусто. Создай стол — если появится пара с той же ставкой, зайдёшь в неё.</p>
          ) : (
            <div className="casino-duel-list">
              {group.duels.map((duel) => (
                <CasinoDuelMatchRow
                  key={duel.game_id}
                  duel={duel}
                  mine={duel.is_mine || mine.includes(duel.game_id)}
                  busy={busy}
                  onOpen={() => navigate(casinoTo(`/casino/duels/${duel.game_id}`))}
                  onJoin={() => void onJoinRow(duel)}
                />
              ))}
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
