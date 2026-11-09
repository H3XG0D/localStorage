import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  getCasinoRaffle,
  getCasinoRaffleCampaigns,
  type CasinoRaffleCampaign,
  type CasinoRafflePlayer,
  type CasinoRaffleSnapshot,
} from "@/lib/public";
import { API_BASE, getToken } from "@/lib/api";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CasinoPlayerAvatar, CasinoPlayerChip } from "./CasinoPlayerChip";
import { WEIGHTED_REEL_SPIN_MS, WEIGHTED_REEL_WINNER_INDEX, buildWeightedReel } from "./weightedReel";

const SLOT_DESKTOP_PX = 72;
const SLOT_MOBILE_PX = 56;
const WINNER_INDEX = WEIGHTED_REEL_WINNER_INDEX;
const SPIN_MS = WEIGHTED_REEL_SPIN_MS;
const RAFFLE_PLAY = "/casino/play/raffle";

function slotPx(): number {
  try {
    if (window.matchMedia("(max-width: 767px)").matches) return SLOT_MOBILE_PX;
  } catch {
    /* SSR */
  }
  return SLOT_DESKTOP_PX;
}

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₽`;
}

function reduceMotion(): boolean {
  try {
    if (document.documentElement.classList.contains("casino-reduce-motion")) return true;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

function buildReel(players: CasinoRafflePlayer[], winnerId: number | null): CasinoRafflePlayer[] {
  return buildWeightedReel(players, (row) => row.tickets, winnerId);
}

function clockLabel(iso: string | null | undefined, spinning: boolean, _now: number): string {
  if (spinning) return "крутится";
  if (!iso) return "—";
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return "—";
  const left = Math.max(0, Math.round((at - _now) / 1000));
  const hours = Math.floor(left / 3600);
  const mm = String(Math.floor((left % 3600) / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  if (hours > 0) return `${hours}:${mm}:${ss}`;
  return `${mm}:${ss}`;
}

function heroPrizeLabel(data: CasinoRaffleSnapshot | null): string {
  if (!data) return "—";
  if (data.next_prize_rub != null) return formatRub(data.next_prize_rub);
  if (data.status === "drawn" && data.last_winner) return formatRub(data.last_winner.prize_rub);
  return "—";
}

function monthKeyOf(row: CasinoRaffleCampaign): string {
  if (row.month_key && /^\d{4}-\d{2}$/.test(row.month_key)) return row.month_key;
  const iso = row.draw_at || row.ends_at;
  if (iso) {
    const at = Date.parse(iso);
    if (Number.isFinite(at)) {
      try {
        const parts = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Moscow", year: "numeric", month: "2-digit" }).format(at);
        if (/^\d{4}-\d{2}$/.test(parts)) return parts;
      } catch { /* ignore */ }
    }
  }
  return "other";
}

function monthTitle(key: string, rows: CasinoRaffleCampaign[]): string {
  if (key === "other") return "Другие";
  const row = rows.find((r) => r.month_label);
  if (row?.month_label) return row.month_label;
  const [y, m] = key.split("-").map(Number);
  if (y && m) {
    try {
      const label = new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", month: "long", year: "numeric" }).format(new Date(Date.UTC(y, m - 1, 15)));
      return label.charAt(0).toUpperCase() + label.slice(1);
    } catch { /* ignore */ }
  }
  return key;
}

function kindBadge(kind: string | null | undefined): string {
  return kind === "weekly" ? "Недельный" : "Главный месячный";
}

function campaignStatusLabel(status: string): string {
  if (status === "drawing") return "идёт розыгрыш";
  if (status === "drawn") return "завершён";
  if (status === "closed") return "приём закрыт";
  return "идёт приём билетов";
}

function mskLabel(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return null;
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow",
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(at);
  } catch {
    return null;
  }
}

function winnerChanceLabel(winner: { chance_pct?: number; tickets?: number; eligible_tickets?: number } | undefined): string | null {
  if (!winner) return null;
  if (typeof winner.chance_pct === "number" && Number.isFinite(winner.chance_pct) && winner.chance_pct > 0) {
    return `${winner.chance_pct.toFixed(1)}%`;
  }
  const tickets = Number(winner.tickets ?? 0);
  const eligible = Number(winner.eligible_tickets ?? 0);
  if (tickets > 0 && eligible > 0) return `${((tickets / eligible) * 100).toFixed(1)}%`;
  return null;
}

function Avatar({ player, size = 48 }: { player: CasinoRafflePlayer; size?: number }) {
  return <CasinoPlayerAvatar actor={player} size={size} className="casino-jackpot-avatar-img" />;
}

function MonthTabs({ campaigns, activeId, onSelect }: { campaigns: CasinoRaffleCampaign[]; activeId: number | null; onSelect: (id: number) => void }) {
  const groups = new Map<string, CasinoRaffleCampaign[]>();
  for (const row of campaigns) {
    const key = monthKeyOf(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(row);
  }
  const keys = [...groups.keys()].sort().reverse();
  const activeRow = campaigns.find((r) => r.campaign_id === activeId);
  const [monthSel, setMonthSel] = useState<string | null>(null);
  const month = monthSel ?? (activeRow ? monthKeyOf(activeRow) : keys[0] ?? "other");
  const rows = (groups.get(month) ?? []).slice().sort((a, b) => {
    const ka = a.kind === "monthly" ? 0 : 1;
    const kb = b.kind === "monthly" ? 0 : 1;
    if (ka !== kb) return ka - kb;
    return (Date.parse(a.draw_at ?? "") || 0) - (Date.parse(b.draw_at ?? "") || 0);
  });
  return (
    <div>
      <div className="casino-raffle-tabs" role="tablist" aria-label="Месяцы">
        {keys.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={month === key}
            className={`casino-raffle-tab${month === key ? " is-active" : ""}`}
            onClick={() => setMonthSel(key)}
          >
            <strong>{monthTitle(key, groups.get(key) ?? [])}</strong>
            <span>{(groups.get(key) ?? []).length} розыгр.</span>
          </button>
        ))}
      </div>
      <div className="casino-raffle-tabs" role="tablist" aria-label="Розыгрыши месяца">
        {rows.map((row) => {
          const active = activeId === row.campaign_id;
          const done = row.status === "drawn";
          return (
            <button
              key={row.campaign_id}
              type="button"
              role="tab"
              aria-selected={active}
              className={`casino-raffle-tab${active ? " is-active" : ""}`}
              data-casino-raffle-tab={row.campaign_id}
              onClick={() => onSelect(row.campaign_id)}
            >
              <strong>{kindBadge(row.kind)} · {done ? "завершён" : row.status === "drawing" || row.status === "closed" ? "ожидает розыгрыша" : "идёт набор"}</strong>
              <span>
                {campaignStatusLabel(row.status)}
                {row.draw_at ? ` · ${mskLabel(row.draw_at)}` : ""}
                {row.my_tickets > 0 ? ` · мои ${row.my_tickets}` : ""}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function CasinoRaffle({ embedded = false }: { embedded?: boolean }) {
  const { isAuthed, loading } = useSession();
  const navigate = useNavigate();
  const [data, setData] = useState<CasinoRaffleSnapshot | null>(null);
  const [campaigns, setCampaigns] = useState<CasinoRaffleCampaign[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [spinning, setSpinning] = useState(false);
  const [shift, setShift] = useState(0);
  const [spinEase, setSpinEase] = useState(false);
  const [spinPlayers, setSpinPlayers] = useState<CasinoRafflePlayer[]>([]);
  const [spinWinnerId, setSpinWinnerId] = useState<number | null>(null);
  const [spinPlace, setSpinPlace] = useState<number | null>(null);
  const spinningRef = useRef(false);
  const spunKeyRef = useRef<string | null>(null);
  const dataRef = useRef<CasinoRaffleSnapshot | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const spinTimer = useRef<number>(0);
  const pendingKick = useRef(false);
  const startSpinRef = useRef<(players: CasinoRafflePlayer[], winnerId: number, place: number, key: string) => void>(() => {});

  const applySnap = useCallback((snap: CasinoRaffleSnapshot) => {
    setData(snap);
    dataRef.current = snap;
  }, []);

  const load = useCallback(async () => {
    if (spinningRef.current) return;
    try {
      const snap = await getCasinoRaffle(selectedId);
      applySnap(snap);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить FocusLucky");
    }
  }, [applySnap, selectedId]);

  const loadCampaigns = useCallback(async () => {
    try {
      const res = await getCasinoRaffleCampaigns();
      setCampaigns(res.campaigns ?? []);
    } catch {
      /* архив необязателен */
    }
  }, []);

  const startSpin = useCallback((players: CasinoRafflePlayer[], winnerId: number, place: number, key: string) => {
    if (spinningRef.current) return;
    if (spunKeyRef.current === key) return;
    spunKeyRef.current = key;
    spinningRef.current = true;
    pendingKick.current = true;
    setSpinPlayers(players);
    setSpinWinnerId(winnerId);
    setSpinPlace(place);
    setSpinning(true);
  }, []);
  startSpinRef.current = startSpin;

  useLayoutEffect(() => {
    if (!spinning || !pendingKick.current) return;
    pendingKick.current = false;
    const slot = slotPx();
    const viewport =
      viewportRef.current?.clientWidth ||
      viewportRef.current?.parentElement?.clientWidth ||
      Math.min(window.innerWidth - 24, 640);
    const target = WINNER_INDEX * slot + slot / 2 - viewport / 2;
    if (reduceMotion()) {
      setSpinEase(false);
      setShift(target);
      window.setTimeout(() => {
        spinningRef.current = false;
        setSpinning(false);
        void load();
      }, 50);
      return;
    }
    setSpinEase(false);
    setShift(0);
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        setSpinEase(true);
        setShift(target);
      });
    });
    window.clearTimeout(spinTimer.current);
    spinTimer.current = window.setTimeout(() => {
      spinningRef.current = false;
      setSpinning(false);
      void load();
    }, SPIN_MS + 200);
  }, [load, spinning]);

  useEffect(() => {
    if (loading) return;
    if (!isAuthed) {
      goCasinoLogin(navigate, RAFFLE_PLAY);
      return;
    }
    void load();
    void loadCampaigns();
  }, [isAuthed, load, loadCampaigns, loading, navigate]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!isAuthed) return;
    void loadCampaigns();
  }, [isAuthed, data?.status, data?.campaign_id, loadCampaigns]);

  useEffect(() => {
    if (!isAuthed) return;
    const token = getToken("user");
    const qs = token ? `?access_token=${encodeURIComponent(token)}` : "";
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/user/casino/raffle/events${qs}`, { withCredentials: true });
      es.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as {
            type?: string;
            campaign_id?: number;
            place?: number;
            winner_id?: number;
            players?: CasinoRafflePlayer[];
          };
          const viewingLive =
            !payload.campaign_id || !dataRef.current || dataRef.current.campaign_id === payload.campaign_id;
          if (viewingLive && payload.type === "spin" && payload.winner_id && payload.place && payload.players?.length) {
            const key = `${payload.campaign_id ?? ""}-${payload.place}`;
            startSpinRef.current(payload.players, payload.winner_id, payload.place, key);
            return;
          }
          if (!viewingLive) {
            void loadCampaigns();
            return;
          }
          if (!spinningRef.current) void load();
        } catch {
          if (!spinningRef.current) void load();
        }
      };
    } catch {
      /* poll */
    }
    const poll = window.setInterval(() => {
      if (!spinningRef.current) void load();
    }, 2000);
    return () => {
      es?.close();
      window.clearInterval(poll);
    };
  }, [isAuthed, load, loadCampaigns]);

  useEffect(() => () => window.clearTimeout(spinTimer.current), []);

  const reelSource = spinning ? spinPlayers : data?.players ?? [];
  const winnerId = spinning ? spinWinnerId : data?.last_winner?.user_id ?? null;
  const reel = useMemo(() => buildReel(reelSource, winnerId), [reelSource, winnerId]);
  const showReel = spinning;
  const clockTarget =
    spinning || data?.status === "drawing"
      ? data?.next_spin_at
      : data?.status === "drawn" || data?.status === "none"
        ? null
        : data?.draw_at;
  const clock = clockLabel(clockTarget, spinning, now);
  const mine = data?.my_user_id ? data.players.find((row) => row.user_id === data.my_user_id) : null;
  const listed = data?.players ?? [];
  const sorted = mine ? [mine, ...listed.filter((row) => row.user_id !== mine.user_id)] : listed;
  const places = data?.prize_places ?? [];
  const winners = data?.winners ?? [];
  const winnersByPlace = new Map(winners.map((row) => [row.place, row]));
  const livePlace = spinning && spinPlace ? spinPlace : data?.next_place ?? data?.current_place ?? null;
  const status = data?.status ?? "none";
  const phase: "none" | "before" | "show" | "done" =
    status === "none" ? "none" : status === "drawn" ? "done" : spinning || status === "drawing" ? "show" : "before";
  const paidTotal = winners.reduce((sum, row) => sum + Number(row.prize_rub || 0), 0);
  const myTickets = data?.my_tickets ?? 0;
  const myChance = data?.my_chance_pct ?? 0;
  const drawAtLabel = mskLabel(data?.draw_at);
  const heroStats: Array<{ label: string; value: string }> =
    phase === "show"
      ? [
          { label: "Место", value: livePlace ? (places.length ? `${livePlace} из ${places.length}` : String(livePlace)) : "—" },
          { label: "Приз места", value: heroPrizeLabel(data) },
          { label: "До спина", value: clock },
        ]
      : phase === "done"
        ? [
            { label: "Розыгрыш", value: "Завершён" },
            { label: "Разыграно", value: formatRub(paidTotal) },
            { label: "Победителей", value: String(winners.length) },
          ]
        : [
            { label: "До старта", value: clock },
            { label: "Призовой фонд", value: formatRub(data?.prize_pool_rub ?? 0) },
            { label: "Мои билеты", value: myTickets > 0 ? `${myTickets} · ${myChance.toFixed(1)}%` : "0" },
          ];
  const fairnessHref = data?.commit_hash && data.campaign_id
    ? `/casino/fairness?game_type=raffle&game_id=flucky-${data.campaign_id}&commit=${encodeURIComponent(data.commit_hash)}&server_seed=${encodeURIComponent(data.server_seed || "")}&client_seed=focuspay&nonce=${data.last_winner?.place ?? 1}&total_tickets=${data.last_winner?.eligible_tickets ?? data.remaining_tickets}&expected_ticket=${data.last_winner?.hmac_index ?? ""}`
    : "/casino/fairness?game_type=raffle";

  return (
    <div className="casino-jackpot" data-casino-raffle="1" data-casino-jackpot-phase={spinning ? "spin" : "wait"}>
      {embedded ? null : (
        <nav className="casino-crumb" aria-label="Навигация">
          <Link to={casinoTo("/casino")}>Лобби</Link>
          <span className="casino-crumb-sep" aria-hidden>/</span>
          <span>FocusLucky</span>
        </nav>
      )}
      {campaigns.length > 1 ? (
        <MonthTabs
          campaigns={campaigns}
          activeId={data?.campaign_id ?? null}
          onSelect={(id) => {
            spunKeyRef.current = null;
            setSelectedId(id);
          }}
        />
      ) : null}
      {phase === "none" ? null : (
        <p className="casino-raffle-caption">
          <span>{data?.title || "FocusLucky"}</span>
          {data?.month_label ? <span>{data.month_label}</span> : null}
          {drawAtLabel ? <span>{phase === "done" ? `розыгрыш ${drawAtLabel} МСК` : `старт ${drawAtLabel} МСК`}</span> : null}
        </p>
      )}
      <header className="casino-raffle-hero">
        {heroStats.map((stat) => (
          <div className="casino-jackpot-hero" key={stat.label}>
            <span>{stat.label}</span>
            <strong>{stat.value}</strong>
          </div>
        ))}
      </header>
      <p className="casino-muted casino-jackpot-rules">
        {phase === "done"
          ? "Розыгрыш завершён. Призы зачислены победителям, билеты нового цикла копятся за обмены."
          : `Билеты за обмены. Шанс = доля оставшихся билетов на это место. Победитель выбывает, через ${data?.spin_interval_seconds ?? 30} с — следующее место.`}
      </p>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {phase === "none" ? <p className="casino-muted">Сейчас нет кампании FocusLucky.</p> : null}

      <div className={`casino-jackpot-reel${showReel ? " is-live" : " is-idle"}`} ref={viewportRef} data-casino-jackpot-reel={showReel ? "spin" : "wait"} aria-hidden={!showReel}>
        {showReel ? (
          <>
            <div className="casino-jackpot-tick" aria-hidden="true" />
            <div className={`casino-jackpot-track${spinEase ? " is-spinning" : ""}`} style={{ transform: `translateX(${-shift}px)` }}>
              {reel.map((player, index) => (
                <div
                  key={`${player.user_id}-${index}`}
                  className={`casino-jackpot-slot${winnerId === player.user_id && index === WINNER_INDEX && !spinning ? " is-winner" : ""}`}
                  style={{ width: slotPx(), minWidth: slotPx() }}
                >
                  <Avatar player={player} />
                </div>
              ))}
            </div>
          </>
        ) : null}
      </div>

      {places.length ? (
        <ol className="casino-raffle-places" data-casino-raffle-places={places.length}>
            {places.map((place) => {
            const winner = winnersByPlace.get(place.place);
            const isNext = livePlace === place.place;
            const chance = winnerChanceLabel(winner);
            return (
              <li
                key={place.place}
                className={winner ? "is-won" : isNext ? "is-next" : undefined}
                data-casino-raffle-place={place.place}
              >
                <strong>{place.place} место</strong>
                {winner ? (
                  <span className="casino-raffle-winner">
                    <CasinoPlayerChip actor={winner} size={24} />
                    {chance ? <span className="casino-raffle-chance">{chance}</span> : null}
                  </span>
                ) : (
                  <span className="casino-raffle-pending">{isNext && phase === "show" ? "крутится…" : "ждёт розыгрыша"}</span>
                )}
                <em>{formatRub(place.prize_rub)}</em>
              </li>
            );
          })}
        </ol>
      ) : null}

      {sorted.length === 0 ? (
        phase === "done" || phase === "none" ? null : (
          <p className="casino-muted casino-jackpot-empty">Пока нет билетов в пуле.</p>
        )
      ) : (
        <>
        <p className="casino-raffle-list-head">
          {phase === "done" ? "Участники розыгрыша" : "В пуле"} · {data?.remaining_tickets ?? 0} бил. · {sorted.length} чел.
        </p>
        <ul className="casino-jackpot-list casino-raffle-list">
          {sorted.map((player) => (
            <li key={player.user_id} className={player.user_id === data?.my_user_id ? "is-mine" : undefined}>
              <CasinoPlayerChip actor={player} size={32} />
              <span className="casino-jackpot-list-meta">
                <strong>{player.tickets} бил.</strong>
                <em>{player.chance_pct.toFixed(1)}%</em>
              </span>
              <span className="casino-jackpot-bar" aria-hidden="true">
                <i style={{ width: `${Math.min(100, Math.max(0, player.chance_pct))}%` }} />
              </span>
            </li>
          ))}
        </ul>
        </>
      )}

      <p className="casino-jackpot-fair">
        {document.documentElement.dataset.exchangeEntry === "tg" ? (
          <a href={`https://focuspay.org${fairnessHref}`}>Честность</a>
        ) : (
          <Link to={casinoTo(fairnessHref)}>Честность</Link>
        )}
        {data?.commit_hash ? <code>{data.commit_hash.slice(0, 12)}…</code> : null}
      </p>
    </div>
  );
}
