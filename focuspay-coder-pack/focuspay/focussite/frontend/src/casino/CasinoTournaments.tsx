import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { Clock3, Coins, Crown, Medal, Trophy, Users } from "lucide-react";
import { toast } from "sonner";
import { API_BASE, ApiError, getToken } from "@/lib/api";
import {
  getCasinoTournament,
  getCasinoTournaments,
  joinCasinoTournament,
  rebuyCasinoTournament,
  setCasinoTournamentWallet,
  type CasinoTournamentListRow,
  type CasinoTournamentPlayer,
  type CasinoTournamentSnapshot,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { CasinoPlayerAvatar } from "./CasinoPlayerChip";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CASINO_BALANCE_EVENT, CASINO_TOURNAMENT_EVENT } from "./gameCatalog";
import { notifyWalletChanged } from "./walletScope";

const CHIPS = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const RUB = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

function chipsLabel(value: number): string {
  return `${CHIPS.format(Math.max(0, value))} фишек`;
}

function rubLabel(value: number): string {
  return `${RUB.format(Math.max(0, value))} ₽`;
}

function clock(seconds: number | null): string {
  if (seconds == null) return "—";
  const total = Math.max(0, seconds);
  if (total >= 86400) {
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    return `${days} д ${hours} ч`;
  }
  const h = Math.floor(total / 3600);
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
}

function entryLabel(row: { entry_mode: string; entry_fee_rub: number }): string {
  if (row.entry_mode === "free") return "Вход свободный";
  if (row.entry_mode === "promo") return "Вход по промокоду";
  if (row.entry_mode === "paid") return `Взнос ${rubLabel(row.entry_fee_rub)}`;
  return `Промокод или ${rubLabel(row.entry_fee_rub)}`;
}

function statusTone(status: string): string {
  if (status === "active") return "is-live";
  if (status === "registration") return "is-soon";
  if (status === "finished") return "is-done";
  return "";
}

function placeIcon(place: number) {
  if (place === 1) return <Crown size={18} aria-hidden />;
  if (place === 2) return <Trophy size={18} aria-hidden />;
  return <Medal size={18} aria-hidden />;
}

export function CasinoTournaments() {
  const { tournamentId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthed } = useSession();
  const [list, setList] = useState<CasinoTournamentListRow[]>([]);
  const [data, setData] = useState<CasinoTournamentSnapshot | null>(null);
  const [selected, setSelected] = useState<number | null>(tournamentId ? Number(tournamentId) : null);
  const [promo, setPromo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const loadedAt = useRef(Date.now());

  const loadList = useCallback(async () => {
    try {
      const res = await getCasinoTournaments();
      const rows = Array.isArray(res.tournaments) ? res.tournaments : [];
      setList(rows);
      setSelected((current) => current ?? rows[0]?.tournament_id ?? null);
    } catch {
      setList([]);
    }
  }, []);

  const loadBracket = useCallback(async (id: number) => {
    try {
      const snap = await getCasinoTournament(id);
      setData(snap);
      loadedAt.current = Date.now();
      setError("");
    } catch (err) {
      setData(null);
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить турнир");
    }
  }, []);

  useEffect(() => {
    if (!isAuthed) return;
    void loadList();
  }, [isAuthed, loadList]);

  useEffect(() => {
    if (!isAuthed || selected == null) return;
    void loadBracket(selected);
    const poll = window.setInterval(() => void loadBracket(selected), 5000);
    return () => window.clearInterval(poll);
  }, [isAuthed, loadBracket, selected]);

  useEffect(() => {
    if (!isAuthed || selected == null) return;
    const token = getToken("user");
    const qs = token ? `?access_token=${encodeURIComponent(token)}` : "";
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/user/casino/tournaments/${selected}/events${qs}`, {
        withCredentials: true,
      });
      es.onmessage = () => void loadBracket(selected);
    } catch {
      es = null;
    }
    return () => es?.close();
  }, [isAuthed, loadBracket, selected]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const secondsLeft = useMemo(() => {
    if (data?.seconds_left == null) return null;
    const drift = Math.floor((now - loadedAt.current) / 1000);
    return Math.max(0, data.seconds_left - drift);
  }, [data?.seconds_left, now]);

  const podium = data?.prize_places.slice(0, 3) ?? [];
  const live = data?.status === "active";
  const open = live || data?.status === "registration";
  const joined = Boolean(data?.me);
  const needsPromo = data?.entry_mode === "promo" || data?.entry_mode === "promo_or_paid";
  const canRebuy =
    joined &&
    live &&
    Boolean(data?.rebuy_enabled) &&
    (data?.max_rebuys_per_user === 0 || (data?.me?.rebuys_count ?? 0) < (data?.max_rebuys_per_user ?? 0));

  async function onJoin() {
    if (!isAuthed) {
      goCasinoLogin(navigate, `${location.pathname}${location.search}`);
      return;
    }
    if (selected == null || busy) return;
    setBusy(true);
    try {
      const snap = await joinCasinoTournament(selected, promo.trim().toUpperCase() || undefined);
      setData(snap);
      loadedAt.current = Date.now();
      setPromo("");
      setError("");
      toast.success(`Вы в турнире · ${chipsLabel(snap.starting_chips)}`);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      window.dispatchEvent(new Event(CASINO_TOURNAMENT_EVENT));
      notifyWalletChanged();
      void loadList();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Не удалось зарегистрироваться";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function onRebuy() {
    if (selected == null || busy) return;
    setBusy(true);
    try {
      const snap = await rebuyCasinoTournament(selected);
      setData(snap);
      loadedAt.current = Date.now();
      toast.success("Стек докуплен");
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      window.dispatchEvent(new Event(CASINO_TOURNAMENT_EVENT));
      notifyWalletChanged();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Не удалось докупить стек";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function onPlay() {
    if (selected == null || busy) return;
    setBusy(true);
    try {
      await setCasinoTournamentWallet(selected);
      window.dispatchEvent(new Event(CASINO_TOURNAMENT_EVENT));
      notifyWalletChanged();
      toast.success("Кошелёк турнира включён — ставки идут фишками");
      navigate(casinoTo("/casino"));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Не удалось включить турнирный кошелёк";
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  if (!isAuthed) {
    return (
      <div className="casino-tournaments" data-casino-tournaments="">
        <header className="casino-section-head">
          <h1 className="casino-section-title">
            <Trophy size={21} aria-hidden /> Турниры
          </h1>
        </header>
        <p className="casino-muted">
          Войдите, чтобы зарегистрироваться в турнире и получить турнирный баланс.
        </p>
        <button type="button" className="casino-btn" onClick={() => goCasinoLogin(navigate, `${location.pathname}${location.search}`)}>
          Войти
        </button>
      </div>
    );
  }

  return (
    <div className="casino-tournaments" data-casino-tournaments="">
      <header className="casino-section-head">
        <h1 className="casino-section-title">
          <Trophy size={21} aria-hidden /> Турниры
        </h1>
        <span className="casino-muted">Играйте на турнирные фишки — призы приходят рублями</span>
      </header>

      {list.length === 0 ? (
        <p className="casino-muted">Сейчас нет ни одного турнира. Загляните позже.</p>
      ) : (
        <div className="casino-trn-tabs" role="tablist" aria-label="Турниры">
          {list.map((row) => (
            <button
              key={row.tournament_id}
              type="button"
              role="tab"
              aria-selected={row.tournament_id === selected}
              data-casino-trn-tab={row.tournament_id}
              className={`casino-trn-tab ${statusTone(row.status)}${row.tournament_id === selected ? " is-active" : ""}`}
              onClick={() => setSelected(row.tournament_id)}
            >
              <em>{row.status_label}</em>
              <strong>{row.title}</strong>
              <span>
                {rubLabel(row.prize_pool_rub)} · {entryLabel(row)}
              </span>
              <span className="casino-trn-tab-meta">
                <Users size={13} aria-hidden /> {row.player_count}/{row.max_participants}
                {row.joined ? ` · ваш стек ${CHIPS.format(row.my_chips ?? 0)}` : ""}
              </span>
            </button>
          ))}
        </div>
      )}

      {data?.tournament_id ? (
        <>
          <section className="casino-trn-hero" data-casino-trn-hero={data.status}>
            <div className="casino-trn-hero-copy">
              <span className={`casino-trn-badge ${statusTone(data.status)}`}>{data.status_label}</span>
              <h2>{data.title}</h2>
              {data.subtitle ? <p className="casino-muted">{data.subtitle}</p> : null}
              <ul className="casino-trn-facts">
                <li>
                  <Coins size={15} aria-hidden /> Стартовый стек {chipsLabel(data.starting_chips)}
                </li>
                <li>
                  <Trophy size={15} aria-hidden /> Призовой фонд {rubLabel(data.prize_pool_rub)}
                </li>
                <li>
                  <Users size={15} aria-hidden /> {data.player_count} из {data.max_participants} мест
                </li>
                <li>{entryLabel(data)}</li>
                <li>
                  {data.rebuy_enabled
                    ? `Докупка ${rubLabel(data.rebuy_fee_rub)} за ${chipsLabel(data.rebuy_chips)}${data.max_rebuys_per_user ? ` (до ${data.max_rebuys_per_user} раз)` : ""}`
                    : "Без докупки — один вход"}
                </li>
              </ul>
            </div>
            <div className="casino-trn-clock" data-casino-trn-clock="">
              <Clock3 size={18} aria-hidden />
              <strong>{clock(secondsLeft)}</strong>
              <span>{live ? "до конца турнира" : data.status === "registration" ? "до старта" : "турнир завершён"}</span>
            </div>
          </section>

          <section className="casino-trn-entry" data-casino-trn-entry="">
            {joined ? (
              <div className="casino-trn-me">
                <div>
                  <span className="casino-muted">Ваш турнирный баланс</span>
                  <strong data-casino-trn-my-chips="">{chipsLabel(data.me?.chips_balance ?? 0)}</strong>
                  <span className="casino-muted">
                    {data.me?.rank ? `${data.me.rank} место` : "вне сетки"} ·{" "}
                    {(data.me?.projected_prize_rub ?? 0) > 0
                      ? `приз сейчас ${rubLabel(data.me?.projected_prize_rub ?? 0)}`
                      : "пока вне призов"}
                  </span>
                </div>
                <div className="casino-trn-entry-actions">
                  {live ? (
                    <button type="button" className="casino-btn" disabled={busy} onClick={() => void onPlay()}>
                      Играть в этом турнире
                    </button>
                  ) : null}
                  {canRebuy ? (
                    <button
                      type="button"
                      className="casino-btn casino-btn-ghost"
                      disabled={busy}
                      data-casino-trn-rebuy=""
                      onClick={() => void onRebuy()}
                    >
                      Докупить стек · {rubLabel(data.rebuy_fee_rub)}
                    </button>
                  ) : null}
                </div>
              </div>
            ) : open ? (
              <div className="casino-trn-join">
                <div>
                  <strong>Регистрация в турнир</strong>
                  <p className="casino-muted">
                    {entryLabel(data)} · получите {chipsLabel(data.starting_chips)}
                    {data.require_exchange_history
                      ? data.my_access_granted
                        ? " · вам открыт персональный доступ"
                        : " · только для клиентов с историей обменов"
                      : ""}
                  </p>
                </div>
                {needsPromo ? (
                  <label className="casino-field">
                    Промокод турнира
                    <input
                      className="casino-mono"
                      value={promo}
                      maxLength={32}
                      autoComplete="off"
                      spellCheck={false}
                      placeholder="RACE100"
                      onChange={(event) => {
                        setPromo(event.target.value.toUpperCase());
                        setError("");
                      }}
                    />
                  </label>
                ) : null}
                <button
                  type="button"
                  className="casino-btn"
                  disabled={busy}
                  data-casino-trn-join=""
                  onClick={() => void onJoin()}
                >
                  {busy ? "Отправка…" : "Участвовать"}
                </button>
              </div>
            ) : (
              <p className="casino-muted">Турнир завершён. Итоги и призы — в таблице ниже.</p>
            )}
            {error ? <p className="casino-duel-error">{error}</p> : null}
          </section>

          {podium.length ? (
            <section className="casino-trn-podium" data-casino-trn-podium="">
              {podium.map((place) => (
                <article
                  key={place.place}
                  className={`casino-trn-place casino-trn-place-${place.place}`}
                  data-casino-trn-place={place.place}
                >
                  <span className="casino-trn-place-icon" aria-hidden>
                    {placeIcon(place.place)}
                  </span>
                  <em>{place.place} место</em>
                  <strong>{rubLabel(place.prize_rub)}</strong>
                  {place.leader ? (
                    <span className="casino-trn-place-leader">
                      <CasinoPlayerAvatar actor={place.leader} size={28} />
                      <span>
                        {place.leader.display_name}
                        <small>{chipsLabel(place.leader.chips_balance)}</small>
                      </span>
                    </span>
                  ) : (
                    <span className="casino-muted">место свободно</span>
                  )}
                </article>
              ))}
            </section>
          ) : null}

          <section className="casino-trn-bracket" data-casino-trn-bracket="">
            <header className="casino-section-head">
              <h3 className="casino-section-title">Турнирная сетка</h3>
              <span className="casino-muted">{data.player_count} участников</span>
            </header>
            {data.players.length === 0 ? (
              <p className="casino-muted">Пока никто не зарегистрировался. Будьте первым.</p>
            ) : (
              <ol className="casino-trn-rows">
                {data.players.map((player) => (
                  <TournamentRow
                    key={player.user_id}
                    player={player}
                    leaderChips={data.players[0]?.chips_balance ?? 0}
                    isMe={player.user_id === data.my_user_id}
                    showRebuys={data.rebuy_enabled}
                  />
                ))}
              </ol>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}

function TournamentRow({
  player,
  leaderChips,
  isMe,
  showRebuys,
}: {
  player: CasinoTournamentPlayer;
  leaderChips: number;
  isMe: boolean;
  showRebuys: boolean;
}) {
  const pct = leaderChips > 0 ? Math.max(2, Math.round((player.chips_balance / leaderChips) * 100)) : 0;
  const inPrizes = player.projected_prize_rub > 0;
  return (
    <li
      className={`casino-trn-row${isMe ? " is-me" : ""}${inPrizes ? " is-prize" : ""}`}
      data-casino-trn-row={player.user_id}
    >
      <span className="casino-trn-rank">#{player.rank}</span>
      <CasinoPlayerAvatar actor={player} size={32} />
      <span className="casino-trn-name">
        {player.display_name}
        {isMe ? <em>вы</em> : null}
        <small>
          раундов {player.rounds_played} · побед {player.wins_count}
          {showRebuys ? ` · докупок ${player.rebuys_count}` : ""}
        </small>
      </span>
      <span className="casino-trn-bar" aria-hidden>
        <i style={{ width: `${pct}%` }} />
      </span>
      <span className="casino-trn-chips casino-mono">{CHIPS.format(player.chips_balance)}</span>
      <span className={`casino-trn-prize${inPrizes ? " is-on" : ""}`}>
        {inPrizes ? rubLabel(player.projected_prize_rub) : "—"}
      </span>
    </li>
  );
}
