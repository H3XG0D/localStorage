import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "@/lib/api";
import {
  getCasinoWar,
  getCasinoWars,
  postCasinoWar,
  postCasinoWarAccept,
  postCasinoWarJoin,
  type CasinoWarSide,
  type CasinoWarSnapshot,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CasinoPlayerChip } from "./CasinoPlayerChip";
import { CASINO_BALANCE_EVENT } from "./gameCatalog";

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₽`;
}

function errMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Не удалось выполнить запрос";
}

export function CasinoClanWars({ embedded = false }: { embedded?: boolean }) {
  const { warId } = useParams();
  if (warId) return <CasinoWarPage warId={warId} />;
  return <CasinoWarLobby embedded={embedded} />;
}

function CasinoWarLobby({ embedded }: { embedded: boolean }) {
  const { isAuthed } = useSession();
  const navigate = useNavigate();
  const [list, setList] = useState<CasinoWarSnapshot[] | null>(null);
  const [maxFighters, setMaxFighters] = useState(5);
  const [enabled, setEnabled] = useState(true);
  const [clansEnabled, setClansEnabled] = useState(true);
  const [error, setError] = useState("");
  const [stake, setStake] = useState("50");
  const [fighters, setFighters] = useState("2");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const data = await getCasinoWars();
      setList(data.wars);
      setMaxFighters(data.max_fighters);
      setEnabled(data.enabled);
      setClansEnabled(data.clans_enabled);
      setError("");
    } catch (err) {
      setError(errMessage(err));
    }
  }

  useEffect(() => {
    void load();
  }, [isAuthed]);

  async function create() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/play/clan_war?mode=players");
      return;
    }
    setBusy(true);
    try {
      const war = await postCasinoWar(Number(stake), Number(fighters));
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      navigate(casinoTo(`/casino/wars/${war.war_id}`));
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="casino-wars" data-casino-wars="1">
      {embedded ? null : (
        <header className="casino-duels-head">
          <div>
            <p className="casino-muted">
              <Link to={casinoTo("/casino")}>Лобби</Link>
              {" · "}
              <Link to={casinoTo("/casino/clans")}>Команды</Link>
            </p>
            <h1>Клан vs клан</h1>
          </div>
        </header>
      )}
      <p className="casino-muted">
        Ставка с личного баланса каждого бойца. У клана нет банка. HMAC выбирает победивший клан, банк минус рейк делится
        поровну между его бойцами.
      </p>
      {!clansEnabled ? <p className="casino-duel-error">Кланы выключены.</p> : null}
      {!enabled ? <p className="casino-duel-error">Войны кланов выключены.</p> : null}
      {error ? <p className="casino-duel-error">{error}</p> : null}
      <form
        className="casino-clan-actions"
        onSubmit={(event) => {
          event.preventDefault();
          void create();
        }}
      >
        <label>
          Ставка бойца, ₽
          <input value={stake} onChange={(event) => setStake(event.target.value)} inputMode="decimal" />
        </label>
        <label>
          Бойцов со стороны (1–{maxFighters})
          <input value={fighters} onChange={(event) => setFighters(event.target.value)} inputMode="numeric" min={1} max={maxFighters} />
        </label>
        <button type="submit" className="casino-btn" disabled={busy || !enabled || !clansEnabled}>
          Вызвать
        </button>
      </form>
      <ul className="casino-clan-list">
        {(list ?? []).length === 0 ? <li className="casino-muted">Открытых войн нет.</li> : null}
        {(list ?? []).map((war) => (
          <li key={war.war_id}>
            <Link to={casinoTo(`/casino/wars/${war.war_id}`)} className="casino-clan-row">
              <strong>[{war.challenger?.tag}]</strong>
              <span>vs {war.opponent ? `[${war.opponent.tag}]` : "ожидает"}</span>
              <span>{formatRub(war.stake_rub)} × {war.fighters_needed}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SideBlock({ title, side, needed }: { title: string; side: CasinoWarSide | null; needed: number }) {
  if (!side) return <p className="casino-muted">{title}: нет</p>;
  return (
    <section>
      <h2>
        {title}: [{side.tag}] {side.name} · {side.filled}/{needed}
      </h2>
      <ul className="casino-clan-list">
        {side.fighters.map((fighter) => (
          <li key={fighter.user_id} className="casino-clan-row">
            <CasinoPlayerChip actor={fighter} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function CasinoWarPage({ warId }: { warId: string }) {
  const { isAuthed } = useSession();
  const navigate = useNavigate();
  const [war, setWar] = useState<CasinoWarSnapshot | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setWar(await getCasinoWar(warId));
      setError("");
    } catch (err) {
      setError(errMessage(err));
    }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(timer);
  }, [warId, isAuthed]);

  async function run(fn: () => Promise<CasinoWarSnapshot>) {
    if (!isAuthed) {
      goCasinoLogin(navigate, `/casino/wars/${warId}`);
      return;
    }
    setBusy(true);
    try {
      setWar(await fn());
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!war && !error) return <p className="casino-muted">Загрузка…</p>;
  if (!war) {
    return (
      <div className="casino-wars">
        <p className="casino-duel-error">{error}</p>
        <Link to={casinoTo("/casino/play/clan_war?mode=players")}>К войнам</Link>
      </div>
    );
  }

  return (
    <div className="casino-wars" data-casino-war={war.war_id}>
      <header className="casino-duels-head">
        <div>
          <p className="casino-muted">
            <Link to={casinoTo("/casino/play/clan_war?mode=players")}>Войны</Link>
            {" · "}
            <Link to={casinoTo("/casino/clans")}>Команды</Link>
          </p>
          <h1>
            {formatRub(war.stake_rub)} · {war.fighters_needed} vs {war.fighters_needed}
          </h1>
        </div>
      </header>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      <p>
        Банк {formatRub(war.pot_rub)}
        {war.status === "settled" && war.payout_per_winner_rub != null
          ? ` · каждому победителю ${formatRub(war.payout_per_winner_rub)}`
          : null}
      </p>
      <SideBlock title="Вызов" side={war.challenger} needed={war.fighters_needed} />
      <SideBlock title="Ответ" side={war.opponent} needed={war.fighters_needed} />
      <div className="casino-clan-actions">
        {war.status === "open" && !war.my_side ? (
          <button type="button" className="casino-btn" disabled={busy} onClick={() => void run(() => postCasinoWarAccept(war.war_id))}>
            Принять за свой клан · {formatRub(war.stake_rub)}
          </button>
        ) : null}
        {(war.status === "open" || war.status === "accepted") && war.my_side == null && war.opponent ? (
          <button type="button" className="casino-btn" disabled={busy} onClick={() => void run(() => postCasinoWarJoin(war.war_id))}>
            Сесть бойцом · {formatRub(war.stake_rub)}
          </button>
        ) : null}
        {(war.status === "open" || war.status === "accepted") && war.my_side == null && !war.opponent ? (
          <button type="button" className="casino-btn" disabled={busy} onClick={() => void run(() => postCasinoWarJoin(war.war_id))}>
            Досесть в вызов · {formatRub(war.stake_rub)}
          </button>
        ) : null}
      </div>
      <p className="casino-muted casino-jackpot-fair">
        HMAC commit-reveal. Хеш: <code>{war.commit_hash}</code>
        {war.server_seed && war.hmac_message ? (
          <>
            {" "}
            Сид: <code>{war.server_seed}</code>
            {" · "}
            <Link
              to={casinoTo(
                `/casino/fairness?game_type=clan_war&game_id=${encodeURIComponent(war.war_id)}&commit=${encodeURIComponent(war.commit_hash)}&server_seed=${encodeURIComponent(war.server_seed)}&hmac_message=${encodeURIComponent(war.hmac_message)}&modulus=2&expected_index=${war.winner_index ?? ""}`,
              )}
            >
              Проверить
            </Link>
          </>
        ) : (
          " Сид откроется после расчёта."
        )}
      </p>
    </div>
  );
}
