import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { prefersCasinoReducedMotion } from "./CasinoDice";
import { casinoTo } from "./casinoPaths";
import { CasinoPlayerAvatar, CasinoPlayerChip } from "./CasinoPlayerChip";
import {
  canonicalRouletteBetKey,
  DEFAULT_ROULETTE_BET,
  ROULETTE_BETS,
  ROULETTE_COAST_DEG_PER_MS,
  ROULETTE_DOZEN_KEYS,
  ROULETTE_POCKET_COUNT,
  ROULETTE_SECTOR_DEG,
  ROULETTE_WHEEL_ORDER,
  isRouletteColorBet,
  isRouletteOutsideBet,
  makeRouletteSpinPlan,
  mergeRouletteDraftBySpot,
  rouletteBetSpec,
  rouletteColorLabel,
  rouletteCoverWord,
  roulettePocketColor,
  rouletteRotationFor,
  rouletteSelectedPockets,
  rouletteStraightKey,
  rouletteVisiblePocket,
  toggleRoulettePocket,
  type RouletteBetKey,
  type RouletteBetSpec,
  type RouletteDraftChip,
  type RouletteOutsideBet,
  type RouletteSpinPlan,
  type RouletteSpinRecord,
  type RouletteUiPhase,
} from "./roulette";

/** Wheel geometry in the 320×320 viewBox. */
const CENTER = 160;
const RIM_OUTER = 152;
const SECTOR_OUTER = 146;
const SECTOR_INNER = 104;
const LABEL_RADIUS = 125;

export const ROULETTE_LAUNCH_MS = 900;
export const ROULETTE_SETTLE_MS = 2600;

function polar(radius: number, deg: number): [number, number] {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [CENTER + radius * Math.cos(rad), CENTER + radius * Math.sin(rad)];
}

function sectorPath(index: number): string {
  const from = (index - 0.5) * ROULETTE_SECTOR_DEG;
  const to = (index + 0.5) * ROULETTE_SECTOR_DEG;
  const [x1, y1] = polar(SECTOR_OUTER, from);
  const [x2, y2] = polar(SECTOR_OUTER, to);
  const [x3, y3] = polar(SECTOR_INNER, to);
  const [x4, y4] = polar(SECTOR_INNER, from);
  return [
    `M ${x1.toFixed(2)} ${y1.toFixed(2)}`,
    `A ${SECTOR_OUTER} ${SECTOR_OUTER} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`,
    `L ${x3.toFixed(2)} ${y3.toFixed(2)}`,
    `A ${SECTOR_INNER} ${SECTOR_INNER} 0 0 0 ${x4.toFixed(2)} ${y4.toFixed(2)}`,
    "Z",
  ].join(" ");
}

const SECTORS = ROULETTE_WHEEL_ORDER.map((pocket, index) => ({
  pocket,
  index,
  color: roulettePocketColor(pocket),
  path: sectorPath(index),
  label: polar(LABEL_RADIUS, index * ROULETTE_SECTOR_DEG),
  labelDeg: index * ROULETTE_SECTOR_DEG,
}));

export type RouletteTableSeat = {
  id?: number;
  user_id: number;
  display_name: string;
  initial: string;
  avatar_url?: string | null;
  bet: string;
  stake_rub: number;
  draft?: boolean;
};

function seatsOnOutside(seats: readonly RouletteTableSeat[], key: string): RouletteTableSeat[] {
  return seats.filter((seat) => seat.bet === key);
}

function seatsOnPocket(seats: readonly RouletteTableSeat[], pocket: number): RouletteTableSeat[] {
  return seats.filter((seat) => {
    if (isRouletteOutsideBet(seat.bet)) return false;
    return rouletteBetSpec(seat.bet).pockets.includes(pocket);
  });
}

function spotStake(seats: readonly RouletteTableSeat[]): number {
  return seats.reduce((sum, seat) => sum + (Number(seat.stake_rub) || 0), 0);
}

function chipLabel(amount: number): string {
  if (!Number.isFinite(amount) || amount <= 0) return "";
  if (Number.isInteger(amount)) return String(amount);
  return String(Math.round(amount * 100) / 100);
}

function seatKey(seat: RouletteTableSeat, index: number): string {
  if (seat.id != null) return String(seat.id);
  return `${seat.user_id}:${seat.bet}:${index}`;
}

function TableChipStack({
  seats,
  mineId,
}: {
  seats: readonly RouletteTableSeat[];
  mineId?: number | null;
}) {
  if (!seats.length) return null;
  const total = spotStake(seats);
  return (
    <>
      {total > 0 ? <span className="casino-roulette-spot-amt">{chipLabel(total)}</span> : null}
      <span className="casino-roulette-table-chips">
        {seats.slice(0, 4).map((seat, index) => {
          const mine = mineId != null && seat.user_id === mineId;
          const className = `casino-roulette-table-chip${mine ? " is-mine" : ""}${seat.draft ? " is-draft" : ""}`;
          const title = `${seat.display_name} · ${chipLabel(seat.stake_rub)}`;
          return (
            <span key={seatKey(seat, index)} className={className} title={title}>
              <CasinoPlayerAvatar actor={seat} size={14} />
            </span>
          );
        })}
      </span>
    </>
  );
}

const FELT_COLUMN_SLOTS: readonly { key: RouletteOutsideBet; desktopRow: number; mobileColumn: number }[] = [
  { key: "col3", desktopRow: 1, mobileColumn: 3 },
  { key: "col2", desktopRow: 2, mobileColumn: 2 },
  { key: "col1", desktopRow: 3, mobileColumn: 1 },
];
const FELT_OUTSIDE_KEYS: readonly RouletteOutsideBet[] = ["low", "even", "red", "black", "odd", "high"];

function feltCellStyle(pocket: number): CSSProperties {
  const index = pocket - 1;
  const column = Math.floor(index / 3);
  const position = index % 3;
  return {
    "--desktop-row": 3 - position,
    "--desktop-column": column + 2,
    "--mobile-row": column + 2,
    "--mobile-column": position + 1,
  } as CSSProperties;
}

function namedSpotOn(
  chipMode: boolean,
  mineOn: boolean,
  bet: RouletteBetKey,
  key: RouletteOutsideBet,
): boolean {
  if (chipMode) return mineOn;
  return rouletteBetSpec(bet).key === key;
}

function RoundTimer({ closesAt, status }: { closesAt: string | null; status?: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, []);
  const closed = status === "locked" || status === "spinning";
  const left = closesAt ? Math.max(0, Math.ceil((Date.parse(closesAt) - now) / 1000)) : null;
  const label = closed
    ? "Колесо общее — ставки закрыты"
    : left == null
      ? "Ждём первую ставку"
      : `Ставки ещё ${left} с`;
  const digits = left == null || closed ? "—" : String(left).padStart(2, "0");
  return (
    <div className={`casino-roulette-countdown${left != null && left <= 5 && !closed ? " is-urgent" : ""}`}>
      <strong>{digits}</strong>
      <span className="casino-roulette-timer">{label}</span>
    </div>
  );
}

function paintRotor(
  el: HTMLDivElement | null,
  deg: number,
  durationMs: number,
  easing: string,
) {
  if (!el) return;
  el.style.transitionDuration = `${durationMs}ms`;
  el.style.transitionTimingFunction = easing;
  el.style.transform = `rotate(${deg}deg)`;
}

function RouletteWheel({
  pocket,
  spinning,
  plan,
  selectedPockets,
  onPickPocket,
  picksLocked,
  fastPlay,
  onSettled,
}: {
  pocket: number | null;
  spinning: boolean;
  plan: RouletteSpinPlan | null;
  selectedPockets: readonly number[];
  onPickPocket: (next: number) => void;
  picksLocked: boolean;
  fastPlay: boolean;
  onSettled?: () => void;
}) {
  const skipMotion = prefersCasinoReducedMotion() || fastPlay;
  const rotation = useRef(0);
  const rotorRef = useRef<HTMLDivElement>(null);
  const raf = useRef(0);
  const planRef = useRef(plan);
  const onSettledRef = useRef(onSettled);
  const settledNotified = useRef(false);
  planRef.current = plan;
  onSettledRef.current = onSettled;

  useEffect(() => {
    const el = rotorRef.current;
    const cancelRaf = () => {
      if (raf.current) {
        cancelAnimationFrame(raf.current);
        raf.current = 0;
      }
    };
    const notifySettled = () => {
      if (settledNotified.current) return;
      settledNotified.current = true;
      onSettledRef.current?.();
    };

    if (!spinning) {
      settledNotified.current = false;
      cancelRaf();
      return undefined;
    }

    if (skipMotion) {
      cancelRaf();
      if (pocket != null) {
        rotation.current = rouletteRotationFor(pocket, rotation.current, 0);
        paintRotor(el, rotation.current, 0, "linear");
        notifySettled();
      }
      return undefined;
    }

    if (pocket == null) {
      settledNotified.current = false;
      let last = performance.now();
      const tick = (now: number) => {
        const dt = Math.min(32, now - last);
        last = now;
        rotation.current += ROULETTE_COAST_DEG_PER_MS * dt;
        paintRotor(el, rotation.current, 0, "linear");
        raf.current = requestAnimationFrame(tick);
      };
      raf.current = requestAnimationFrame(tick);
      return cancelRaf;
    }

    cancelRaf();
    const settle = planRef.current ?? makeRouletteSpinPlan(false);
    const from = rotation.current;
    const to = rouletteRotationFor(pocket, from, settle.turns);
    paintRotor(el, from, 0, "linear");
    if (el) void el.offsetWidth;
    paintRotor(el, to, settle.durationMs, settle.easing);
    rotation.current = to;
    const fallback = window.setTimeout(notifySettled, Math.max(80, settle.durationMs + 200));
    const onEnd = (event: TransitionEvent) => {
      if (event.target !== el) return;
      if (event.propertyName && event.propertyName !== "transform") return;
      notifySettled();
    };
    el?.addEventListener("transitionend", onEnd);
    return () => {
      window.clearTimeout(fallback);
      el?.removeEventListener("transitionend", onEnd);
    };
  }, [spinning, pocket, skipMotion]);

  const settled = rouletteVisiblePocket(spinning, pocket);
  const color = settled == null ? null : roulettePocketColor(settled);
  const colorLabel = color == null ? "" : rouletteColorLabel(color);
  const label =
    settled == null ? "Колесо европейской рулетки, 37 лунок" : `Выпало ${settled}, ${colorLabel}`;

  return (
    <div
      className={`casino-roulette-wheel${spinning ? " is-spinning" : ""}`}
      data-casino-roulette-wheel={spinning ? "spinning" : "idle"}
      data-casino-roulette-labels="1"
      role="img"
      aria-label={label}
    >
      <div className="casino-roulette-rotor" ref={rotorRef}>
        <svg viewBox="0 0 320 320" aria-hidden focusable="false">
          <circle cx={CENTER} cy={CENTER} r={RIM_OUTER} className="casino-roulette-rim" />
          {SECTORS.map((sector) => (
            <path
              key={sector.pocket}
              d={sector.path}
              className={`casino-roulette-sector${settled === sector.pocket ? " is-landed" : ""}${
                selectedPockets.includes(sector.pocket) ? " is-picked" : ""
              }`}
              data-color={sector.color}
              onClick={() => {
                if (!picksLocked) onPickPocket(sector.pocket);
              }}
            />
          ))}
          <g className="casino-roulette-numbers">
            {SECTORS.map((sector) => (
              <text
                key={sector.pocket}
                x={sector.label[0]}
                y={sector.label[1]}
                transform={`rotate(${sector.labelDeg} ${sector.label[0]} ${sector.label[1]})`}
                textAnchor="middle"
                dominantBaseline="central"
                className={settled === sector.pocket ? "is-landed" : undefined}
              >
                {sector.pocket}
              </text>
            ))}
          </g>
          <circle cx={CENTER} cy={CENTER} r={SECTOR_INNER} className="casino-roulette-bowl" />
          <circle cx={CENTER} cy={CENTER} r={64} className="casino-roulette-cone" />
          {[0, 90, 180, 270].map((deg) => {
            const [x1, y1] = polar(58, deg);
            const [x2, y2] = polar(96, deg);
            return <line key={deg} x1={x1} y1={y1} x2={x2} y2={y2} className="casino-roulette-spoke" />;
          })}
          <text className="casino-roulette-brand" x={CENTER} y={CENTER - 16} textAnchor="middle">
            FOCUS
          </text>
          <text className="casino-roulette-brand-sub" x={CENTER} y={CENTER - 4} textAnchor="middle">
            EUROPEAN ROULETTE
          </text>
        </svg>
      </div>
      <span className="casino-roulette-pointer" aria-hidden />
    </div>
  );
}

function OutsideSpotButton({
  betKey,
  bet,
  disabled,
  tableSeats,
  mineId,
  chipMode,
  compact,
  caption,
  onChange,
  onPlaceSpot,
  onClearSpot,
}: {
  betKey: RouletteOutsideBet;
  bet: RouletteBetKey;
  disabled: boolean;
  tableSeats: readonly RouletteTableSeat[];
  mineId?: number | null;
  chipMode: boolean;
  compact?: boolean;
  caption?: string;
  onChange: (next: RouletteBetKey) => void;
  onPlaceSpot?: (next: RouletteBetKey) => void;
  onClearSpot?: (next: RouletteBetKey) => void;
}) {
  const spec = ROULETTE_BETS[betKey];
  const onSpot = seatsOnOutside(tableSeats, betKey);
  const mineOn = mineId != null && onSpot.some((seat) => seat.user_id === mineId);
  const on = namedSpotOn(chipMode, mineOn, bet, betKey);
  return (
    <button
      type="button"
      className={`${compact ? "casino-roulette-felt-outside" : "casino-roulette-bet"}${on ? " is-on" : ""}`}
      data-casino-roulette-bet={betKey}
      aria-pressed={on}
      aria-label={chipMode ? `Поставить фишку на ${spec.title.toLowerCase()}` : spec.ariaLabel}
      disabled={disabled}
      onClick={() => {
        if (chipMode) onPlaceSpot?.(betKey);
        else if (betKey === "zero" && !isRouletteColorBet(bet)) onChange(toggleRoulettePocket(bet, 0));
        else onChange(betKey);
      }}
      onContextMenu={
        chipMode && onClearSpot
          ? (event) => {
              event.preventDefault();
              if (mineOn) onClearSpot(betKey);
            }
          : undefined
      }
    >
      {compact ? (
        <>
          <strong>{caption ?? spec.title}</strong>
        </>
      ) : (
        <>
          <span className="casino-roulette-bet-mark" aria-hidden />
          <strong>{spec.title}</strong>
          <span className="casino-roulette-bet-odds">{spec.odds}</span>
        </>
      )}
      <TableChipStack seats={onSpot} mineId={mineId} />
    </button>
  );
}

function draftSeatsOf(
  chips: readonly RouletteDraftChip[],
  actor: Omit<RouletteTableSeat, "bet" | "stake_rub" | "draft">,
): RouletteTableSeat[] {
  return mergeRouletteDraftBySpot(chips).map((chip, index) => ({
    id: -1 - index,
    user_id: actor.user_id,
    display_name: actor.display_name,
    initial: actor.initial,
    avatar_url: actor.avatar_url,
    bet: String(chip.bet),
    stake_rub: chip.amount,
    draft: true,
  }));
}

function RouletteTableActions({
  disabled,
  canRepeat,
  canUndo,
  canClear,
  onRepeat,
  onUndo,
  onClear,
}: {
  disabled: boolean;
  canRepeat: boolean;
  canUndo: boolean;
  canClear: boolean;
  onRepeat?: () => void;
  onUndo?: () => void;
  onClear: () => void;
}) {
  return (
    <div className="casino-roulette-actions" role="group" aria-label="Ставки на столе">
      <button
        type="button"
        className="casino-btn casino-btn-ghost"
        data-casino-roulette-repeat=""
        disabled={disabled || !canRepeat}
        aria-label="Повторить раскладку прошлого раунда"
        onClick={() => onRepeat?.()}
      >
        Повторить
      </button>
      <button
        type="button"
        className="casino-btn casino-btn-ghost"
        data-casino-roulette-undo=""
        disabled={disabled || !canUndo}
        aria-label="Отменить последнюю фишку"
        onClick={() => onUndo?.()}
      >
        Отменить
      </button>
      <button
        type="button"
        className="casino-btn casino-btn-ghost casino-roulette-clear"
        data-casino-roulette-clear=""
        disabled={disabled || !canClear}
        aria-label="Сбросить все свои фишки"
        onClick={onClear}
      >
        Сбросить все
      </button>
    </div>
  );
}

function RouletteNumberGrid({
  bet,
  onChange,
  disabled,
  tableSeats = [],
  mineId,
  onPlaceSpot,
  onClearSpot,
  onClearAll,
  onRepeat,
  onUndoLast,
  canRepeat = false,
  ownStakeRub = 0,
  landedPocket = null,
  groupPockets,
  onGroupToggle,
}: {
  bet: RouletteBetKey;
  onChange: (next: RouletteBetKey) => void;
  disabled: boolean;
  tableSeats?: readonly RouletteTableSeat[];
  mineId?: number | null;
  onPlaceSpot?: (next: RouletteBetKey) => void;
  onClearSpot?: (next: RouletteBetKey) => void;
  onClearAll?: () => void;
  onRepeat?: () => void;
  onUndoLast?: () => void;
  canRepeat?: boolean;
  /** Server stake plus the local log. Seats can miss the viewer id; this still enables undo. */
  ownStakeRub?: number;
  landedPocket?: number | null;
  groupPockets?: ReadonlySet<number>;
  onGroupToggle?: (pocket: number) => void;
}) {
  const spec = rouletteBetSpec(bet);
  const picked = new Set(rouletteSelectedPockets(bet));
  const chipMode = onPlaceSpot != null;
  const mineSeats = mineId == null ? [] : tableSeats.filter((seat) => seat.user_id === mineId);
  const mineStake = Math.max(spotStake(mineSeats), ownStakeRub);
  const cover = picked.size;
  const kicker = onGroupToggle
    ? "Набор: клик отмечает числа, ставка уходит одной кнопкой."
    : chipMode
    ? "Клик сразу ставит. Отменить — последнюю фишку, ПКМ снимает клетку."
    : cover
      ? `${cover} ${rouletteCoverWord(cover)} · ${spec.odds}`
      : "Числа · клик добавляет, выплата 36÷N";
  const canClear = chipMode ? mineStake > 0 : bet !== DEFAULT_ROULETTE_BET;
  return (
    <div
      className="casino-roulette-numbers-bet"
      role="group"
      aria-label={chipMode ? "Фишки на числа" : "Ставка на числа, выплата 36 к числу выбранных"}
    >
      <div className="casino-roulette-numbers-head">
        <p className="casino-roulette-numbers-kicker">{kicker}</p>
        {chipMode ? (
          <RouletteTableActions
            disabled={disabled}
            canRepeat={canRepeat}
            canUndo={mineStake > 0}
            canClear={canClear}
            onRepeat={onRepeat}
            onUndo={onUndoLast}
            onClear={() => onClearAll?.()}
          />
        ) : (
          <button
            type="button"
            className="casino-btn casino-btn-ghost casino-roulette-clear"
            data-casino-roulette-clear=""
            disabled={disabled || !canClear}
            aria-label="Сбросить все свои фишки"
            onClick={() => onChange(DEFAULT_ROULETTE_BET)}
          >
            Сбросить все
          </button>
        )}
      </div>
      <div className="casino-roulette-felt-scroll">
      <div className="casino-roulette-felt">
        <button
          type="button"
          className={`casino-roulette-felt-cell is-zero${onGroupToggle ? (groupPockets?.has(0) ? " is-on" : "") : chipMode ? (mineId != null && seatsOnPocket(tableSeats, 0).some((seat) => seat.user_id === mineId) ? " is-on" : "") : picked.has(0) ? " is-on" : ""}${landedPocket === 0 ? " is-winner" : ""}`}
          data-color="green"
          aria-pressed={onGroupToggle ? Boolean(groupPockets?.has(0)) : chipMode ? mineId != null && seatsOnPocket(tableSeats, 0).some((seat) => seat.user_id === mineId) : picked.has(0)}
          aria-label={onGroupToggle ? "Добавить 0 в набор" : chipMode ? "Поставить фишку на 0" : rouletteBetSpec("0").ariaLabel}
          disabled={disabled}
          onClick={() => {
            if (onGroupToggle) onGroupToggle(0);
            else if (chipMode) onPlaceSpot?.(rouletteStraightKey(0));
            else onChange(toggleRoulettePocket(bet, 0));
          }}
          onContextMenu={
            chipMode && onClearSpot
              ? (event) => {
                  event.preventDefault();
                  const mineOn = mineId != null && seatsOnPocket(tableSeats, 0).some((seat) => seat.user_id === mineId);
                  if (mineOn) onClearSpot(rouletteStraightKey(0));
                }
              : undefined
          }
        >
          0
          <TableChipStack seats={seatsOnPocket(tableSeats, 0)} mineId={mineId} />
        </button>
        {Array.from({ length: 36 }, (_, index) => {
          const pocket = index + 1;
          const color = roulettePocketColor(pocket);
          const key = rouletteStraightKey(pocket);
          const onSpot = seatsOnPocket(tableSeats, pocket);
          const mineOn = mineId != null && onSpot.some((seat) => seat.user_id === mineId);
          const on = onGroupToggle ? Boolean(groupPockets?.has(pocket)) : chipMode ? mineOn : picked.has(pocket);
          return (
            <button
              key={pocket}
              type="button"
              className={`casino-roulette-felt-cell${on ? " is-on" : ""}${landedPocket === pocket ? " is-winner" : ""}`}
              style={feltCellStyle(pocket)}
              data-color={color}
              aria-pressed={on}
              aria-label={
                onGroupToggle
                  ? `Добавить ${pocket} в набор`
                  : chipMode
                  ? `Поставить фишку на ${pocket}`
                  : rouletteBetSpec(String(pocket)).ariaLabel
              }
              disabled={disabled}
              onClick={() => {
                if (onGroupToggle) onGroupToggle(pocket);
                else if (chipMode) onPlaceSpot(key);
                else onChange(toggleRoulettePocket(bet, pocket));
              }}
              onContextMenu={
                chipMode && onClearSpot
                  ? (event) => {
                      event.preventDefault();
                      if (mineOn) onClearSpot(key);
                    }
                  : undefined
              }
            >
              {pocket}
              <TableChipStack seats={onSpot} mineId={mineId} />
            </button>
          );
        })}
        {FELT_COLUMN_SLOTS.map((slot) => (
          <div
            key={slot.key}
            className="casino-roulette-column"
            style={{ "--desktop-row": slot.desktopRow, "--mobile-column": slot.mobileColumn } as CSSProperties}
          >
            <OutsideSpotButton
              betKey={slot.key}
              bet={bet}
              disabled={disabled}
              tableSeats={tableSeats}
              mineId={mineId}
              chipMode={chipMode}
              compact
              caption="2:1"
              onChange={onChange}
              onPlaceSpot={onPlaceSpot}
              onClearSpot={onClearSpot}
            />
          </div>
        ))}
        <div className="casino-roulette-dozens" role="group" aria-label="Ряды 1–12">
          {ROULETTE_DOZEN_KEYS.map((key) => (
            <OutsideSpotButton
              key={key}
              betKey={key}
              bet={bet}
              disabled={disabled}
              tableSeats={tableSeats}
              mineId={mineId}
              chipMode={chipMode}
              compact
              onChange={onChange}
              onPlaceSpot={onPlaceSpot}
              onClearSpot={onClearSpot}
            />
          ))}
        </div>
        <div className="casino-roulette-even-money" role="group" aria-label="Внешние ставки">
          {FELT_OUTSIDE_KEYS.map((key) => (
            <OutsideSpotButton
              key={key}
              betKey={key}
              bet={bet}
              disabled={disabled}
              tableSeats={tableSeats}
              mineId={mineId}
              chipMode={chipMode}
              compact
              onChange={onChange}
              onPlaceSpot={onPlaceSpot}
              onClearSpot={onClearSpot}
            />
          ))}
        </div>
      </div>
      </div>
    </div>
  );
}

function RouletteHistory({ rows }: { rows: readonly RouletteSpinRecord[] }) {
  return (
    <div className="casino-roulette-history-wrap">
      {rows.length ? (
        <ol className="casino-roulette-history" aria-label="Последние результаты">
          {rows.map((row) => {
            const colorLabel = rouletteColorLabel(row.color);
            return (
              <li key={row.id}>
                <span
                  className="casino-roulette-chip"
                  data-color={row.color}
                  title={`${row.pocket} ${colorLabel}`}
                  aria-label={`${row.pocket} ${colorLabel}`}
                >
                  {row.pocket}
                </span>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="casino-muted">История пуста — первый спин её откроет.</p>
      )}
    </div>
  );
}

export interface CasinoRouletteResult {
  pocket: number;
  bet: RouletteBetKey;
  won: boolean;
  stakeRub: number;
  payoutRub: number;
  commit?: string;
}

function phaseCopy(phase: RouletteUiPhase, betSpec: RouletteBetSpec, chance: number): string {
  const cover = betSpec.pockets.length;
  const coverHint =
    cover > 1 && !isRouletteColorBet(betSpec.key)
      ? ` ${cover} ${rouletteCoverWord(cover)}, возврат ×${formatMultiplier(betSpec.payoutMultiplier)}, не ×36.`
      : "";
  if (phase === "spinning") return "Колесо крутится…";
  if (phase === "insufficient") return "Недостаточно средств — уменьшите ставку или пополните кошелёк.";
  if (phase === "invalid") return "Ставка некорректна: сумма должна быть больше нуля и внутри лимита стола.";
  if (phase === "ready") {
    return `Готово. Ставка «${betSpec.title.toLowerCase()}»: выплата ${betSpec.odds}, шанс ${chance.toFixed(1)}%.${coverHint}`;
  }
  return `Клик по числам добавляет их в одну ставку (выплата 36÷N). Сейчас «${betSpec.title.toLowerCase()}», выплата ${betSpec.odds}.`;
}

function formatMultiplier(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return String(rounded).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}

export function CasinoRoulette({
  bet,
  onBetChange,
  betsLocked,
  spinning,
  phase,
  plan,
  result,
  history,
  formatRub,
  tableSeats,
  mineId,
  closesAt,
  tableStatus,
  fastPlay = false,
  onSettled,
  onPlaceSpot,
  onClearSpot,
  onClearAll,
  draftChips = [],
  draftActor,
  onRepeat,
  onUndoLast,
  canRepeat = false,
  ownStakeRub = 0,
  denominations,
  denomination = 0,
  onDenomination,
  denominationDisabled = false,
  denominationMin = 0,
  denominationMax = Number.POSITIVE_INFINITY,
  fairness,
}: {
  bet: RouletteBetKey;
  onBetChange: (next: RouletteBetKey) => void;
  betsLocked: boolean;
  spinning: boolean;
  phase: RouletteUiPhase;
  plan: RouletteSpinPlan | null;
  result: CasinoRouletteResult | null;
  history: readonly RouletteSpinRecord[];
  formatRub: (value: number) => string;
  tableSeats?: readonly RouletteTableSeat[];
  mineId?: number | null;
  closesAt?: string | null;
  tableStatus?: string;
  fastPlay?: boolean;
  onSettled?: () => void;
  onPlaceSpot?: (next: RouletteBetKey) => void;
  onClearSpot?: (next: RouletteBetKey) => void;
  onClearAll?: () => void;
  draftChips?: readonly RouletteDraftChip[];
  draftActor?: Omit<RouletteTableSeat, "bet" | "stake_rub" | "draft"> | null;
  onRepeat?: () => void;
  onUndoLast?: () => void;
  canRepeat?: boolean;
  ownStakeRub?: number;
  denominations?: readonly number[];
  denomination?: number;
  onDenomination?: (amount: number) => void;
  denominationDisabled?: boolean;
  denominationMin?: number;
  denominationMax?: number;
  fairness?: {
    roundId: string;
    commit: string;
    serverSeed?: string | null;
    clientSeed?: string;
    nonce?: number;
  } | null;
}) {
  const [pickMode, setPickMode] = useState<"single" | "group">("single");
  const [groupPockets, setGroupPockets] = useState<number[]>([]);
  useEffect(() => {
    if (spinning) setGroupPockets([]);
  }, [spinning]);
  const seats = tableSeats ?? [];
  const tableMode = tableSeats != null;
  const shown = spinning || !result ? null : tableMode && result.stakeRub <= 0 && !result.won ? null : result;
  const color = shown ? roulettePocketColor(shown.pocket) : null;
  const colorLabel = color ? rouletteColorLabel(color) : "";
  const profit = shown ? Math.round((shown.payoutRub - shown.stakeRub) * 100) / 100 : 0;
  const betSpec = rouletteBetSpec(bet);
  const chance = (betSpec.pockets.length / ROULETTE_POCKET_COUNT) * 100;
  const chipMode = onPlaceSpot != null;
  const groupMode = chipMode && pickMode === "group";
  const groupSet = new Set(groupPockets);
  const overlay =
    chipMode && mineId != null && draftActor
      ? draftSeatsOf(draftChips, { ...draftActor, user_id: mineId })
      : [];
  const feltSeats = overlay.length ? [...seats, ...overlay] : seats;
  const mySeats = mineId == null ? [] : feltSeats.filter((seat) => seat.user_id === mineId);
  const selectedPockets = chipMode
    ? mySeats.flatMap((seat) => rouletteBetSpec(seat.bet).pockets)
    : rouletteSelectedPockets(bet);
  const uniquePlayers = new Set(seats.map((seat) => seat.user_id)).size;
  const draftTotal = spotStake(overlay);
  const myStake = Math.max(spotStake(mySeats), ownStakeRub);
  const stageTitle = spinning ? "Ставки закрыты" : shown ? "Результат раунда" : "Делайте ставки";
  const stageHint = spinning
    ? "Колесо вращается"
    : tableMode
      ? tableStatus === "open"
        ? uniquePlayers
          ? `За столом ${uniquePlayers}. Фишка на клетку списывается сразу.`
          : "Выберите фишку и клетку"
        : phaseCopy(phase, betSpec, chance)
      : phaseCopy(phase, betSpec, chance);

  return (
    <div
      className={`casino-cub-stage casino-roulette${shown ? (shown.won ? " is-win" : " is-lose") : ""}`}
      data-casino-roulette=""
      data-casino-roulette-phase={phase}
      data-casino-roulette-color={color || ""}
      data-casino-roulette-cover={String(betSpec.pockets.length)}
      data-casino-roulette-table={tableMode ? "1" : "0"}
      data-casino-roulette-chips={chipMode ? "1" : "0"}
      data-casino-roulette-fast={fastPlay ? "1" : "0"}
      data-casino-roulette-draft={String(draftTotal)}
    >
      <RouletteHistory rows={history} />
      <div className={`casino-roulette-stage${spinning ? " is-spinning" : ""}${shown ? " is-result" : ""}`}>
        <div className="casino-roulette-round">
          <div className="casino-roulette-round-copy">
            <span className="casino-roulette-eyebrow">{tableMode ? "Общий стол" : "Европейская 0–36"}</span>
            <h2>{stageTitle}</h2>
          </div>
          {tableMode ? <RoundTimer closesAt={closesAt ?? null} status={spinning ? "spinning" : tableStatus} /> : null}
        </div>
        <RouletteWheel
          pocket={result?.pocket ?? null}
          spinning={spinning}
          plan={plan}
          selectedPockets={selectedPockets}
          onPickPocket={(next) => {
            if (groupMode) {
              setGroupPockets((current) => current.includes(next) ? current.filter((pocket) => pocket !== next) : [...current, next]);
              return;
            }
            if (chipMode && onPlaceSpot) onPlaceSpot(rouletteStraightKey(next));
            else onBetChange(toggleRoulettePocket(bet, next));
          }}
          picksLocked={betsLocked}
          fastPlay={fastPlay}
          onSettled={onSettled}
        />
        <div className="casino-roulette-stage-footer">
          <div className="casino-roulette-outcome" role="status">
            {shown ? (
              <>
                <b className="casino-roulette-result-number" data-color={color || ""}>
                  {shown.pocket}
                </b>
                <div>
                  <strong>{colorLabel}</strong>
                  <p>
                    {shown.stakeRub <= 0 ? "Без ставки" : shown.won ? "Вы выиграли" : profit === 0 ? "Возврат ставки" : "Вы проиграли"}
                  </p>
                  {shown.commit ? <p className="casino-mono">commit {shown.commit.slice(0, 16)}…</p> : null}
                </div>
              </>
            ) : (
              <p>{stageHint}</p>
            )}
          </div>
          <dl className="casino-roulette-totals">
            <div>
              <dt>Ваша ставка</dt>
              <dd>{formatRub(shown ? shown.stakeRub : myStake)}</dd>
            </div>
            <div>
              <dt>Выплата</dt>
              <dd>{shown ? formatRub(shown.payoutRub) : "—"}</dd>
            </div>
            <div>
              <dt>Итог</dt>
              <dd>{shown ? `${profit > 0 ? "+" : profit < 0 ? "−" : ""}${formatRub(Math.abs(profit))}` : "—"}</dd>
            </div>
          </dl>
        </div>
      </div>
      {denominations?.length ? (
        <div className="casino-roulette-denoms" data-casino-roulette-chips="">
          <span>Номинал фишки</span>
          <div role="group" aria-label="Номинал фишки">
            {denominations.map((amount) => (
              <button
                key={amount}
                type="button"
                className={Math.abs(denomination - amount) < 0.005 ? "is-on" : ""}
                disabled={denominationDisabled || amount < denominationMin || amount > denominationMax}
                aria-pressed={Math.abs(denomination - amount) < 0.005}
                aria-label={`Фишка ${amount} рублей`}
                onClick={() => onDenomination?.(amount)}
              >
                {amount}
              </button>
            ))}
          </div>
          {chipMode ? (
            <div className="casino-roulette-modes" role="group" aria-label="Режим ставки">
              <button type="button" aria-pressed={pickMode === "single"} onClick={() => { setPickMode("single"); setGroupPockets([]); }}>Одна клетка</button>
              <button type="button" aria-pressed={pickMode === "group"} onClick={() => setPickMode("group")}>Набор чисел</button>
            </div>
          ) : null}
          {groupMode ? (
            <div className="casino-roulette-group">
              <span>{groupPockets.length ? `${[...groupPockets].sort((a, b) => a - b).join(", ")} · ${rouletteBetSpec(canonicalRouletteBetKey(groupPockets)).odds}` : "Выберите несколько чисел на сукне"}</span>
              <button
                type="button"
                className="casino-btn casino-btn-primary"
                disabled={betsLocked || groupPockets.length < 2}
                onClick={() => {
                  onPlaceSpot?.(canonicalRouletteBetKey(groupPockets));
                  setGroupPockets([]);
                }}
              >
                Поставить {formatRub(denomination)} на набор
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
      <RouletteNumberGrid
        bet={bet}
        onChange={onBetChange}
        disabled={betsLocked}
        tableSeats={feltSeats}
        mineId={mineId}
        onPlaceSpot={onPlaceSpot}
        onClearSpot={onClearSpot}
        onClearAll={onClearAll}
        onRepeat={onRepeat}
        onUndoLast={onUndoLast}
        canRepeat={canRepeat}
        ownStakeRub={ownStakeRub}
        landedPocket={shown?.pocket ?? null}
        groupPockets={groupMode ? groupSet : undefined}
        onGroupToggle={groupMode ? (pocket) => setGroupPockets((current) => current.includes(pocket) ? current.filter((item) => item !== pocket) : [...current, pocket]) : undefined}
      />

      {tableMode ? (
        <div className="casino-roulette-bottom">
          <section className="casino-roulette-people" aria-label="За столом">
            <h2>За столом <small>{uniquePlayers}</small></h2>
            {seats.length ? (
              <ul>
                {[...new Map(seats.map((seat) => [seat.user_id, seat])).values()].map((seat) => {
                  const stake = seats.filter((row) => row.user_id === seat.user_id).reduce((sum, row) => sum + row.stake_rub, 0);
                  return (
                    <li key={seat.user_id}>
                      <CasinoPlayerChip actor={seat} size={28} />
                      <span>{mineId != null && seat.user_id === mineId ? "Вы" : seat.display_name}</span>
                      <strong>{formatRub(stake)}</strong>
                    </li>
                  );
                })}
              </ul>
            ) : <p className="casino-muted">Пока никого.</p>}
          </section>
          <section className="casino-roulette-mine" aria-label="Мои ставки">
            <h2>Мои ставки <small>{mySeats.length}</small></h2>
            {mySeats.length ? (
              <ul>
                {mySeats.map((seat, index) => (
                  <li key={seatKey(seat, index)}>
                    <span>{rouletteBetSpec(seat.bet).title}</span>
                    <strong>{formatRub(seat.stake_rub)}</strong>
                  </li>
                ))}
              </ul>
            ) : <p className="casino-muted">Выберите номинал фишки и нажмите на число или тип ставки.</p>}
          </section>
        </div>
      ) : null}
      <details className="casino-roulette-rules">
        <summary>Правила и выплаты</summary>
        <p>Красное и чёрное, чёт и нечет, 1–18 и 19–36: 1:1. Дюжины и колонки: 2:1. Одно число: 35:1. Набор из N чисел: полный возврат ×(36/N). Ноль не входит в цвет, чётность, диапазоны, дюжины и колонки. Ставка списывается сразу.</p>
      </details>
      <details className="casino-roulette-rules">
        <summary>Проверка результата HMAC</summary>
        <p>Коммит раунда публикуется до спина. После остановки сид открывается, и тот же расчёт можно повторить на странице честности.</p>
        {fairness?.commit ? <p className="casino-mono">{fairness.commit}</p> : null}
        <Link to={casinoTo(fairness?.roundId ? `/casino/fairness?game_type=roulette&game_id=${encodeURIComponent(fairness.roundId)}&commit=${encodeURIComponent(fairness.commit)}&server_seed=${encodeURIComponent(fairness.serverSeed || "")}&client_seed=${encodeURIComponent(fairness.clientSeed || "")}&nonce=${fairness.nonce ?? 0}` : "/casino/fairness")}>Открыть проверку</Link>
      </details>
    </div>
  );
}
