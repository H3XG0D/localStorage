import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  actNardyTable,
  getNardyTable,
  getNardyWatch,
  leaveNardyTable,
  type NardyPoint,
  type NardySnapshot,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo } from "./casinoPaths";

const LEFT_TOP = [13, 14, 15, 16, 17, 18];
const RIGHT_TOP = [19, 20, 21, 22, 23, 24];
const LEFT_BOTTOM = [12, 11, 10, 9, 8, 7];
const RIGHT_BOTTOM = [6, 5, 4, 3, 2, 1];
const TOP_ORDER = [...LEFT_TOP, ...RIGHT_TOP];
const BOTTOM_ORDER = [...LEFT_BOTTOM, ...RIGHT_BOTTOM];

const DIE_PIPS: Record<number, number[]> = {
  1: [4],
  2: [0, 8],
  3: [0, 4, 8],
  4: [0, 2, 6, 8],
  5: [0, 2, 4, 6, 8],
  6: [0, 2, 3, 5, 6, 8],
};

type Side = "white" | "black";
type Dest = number | "off";
type Step = { from: number; to: Dest };

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value)} ₽`;
}

function sideName(side: Side | null): string {
  if (side === "white") return "белые";
  if (side === "black") return "чёрные";
  return "—";
}

function pointOf(points: NardyPoint[], point: number): NardyPoint {
  return points.find((item) => item.point === point) ?? { point, white: 0, black: 0 };
}

function isDarkPoint(point: number): boolean {
  const top = TOP_ORDER.indexOf(point);
  if (top >= 0) return top % 2 === 1;
  return BOTTOM_ORDER.indexOf(point) % 2 === 1;
}

function isHome(point: number): boolean {
  return (point >= 1 && point <= 6) || (point >= 13 && point <= 18);
}

function parseLabel(label: string): Step[] | null {
  const text = label.trim();
  if (text === "ход сгорел") return [];
  const steps: Step[] = [];
  for (const part of text.split(",").map((item) => item.trim()).filter(Boolean)) {
    const bear = /^снять с (\d+)$/.exec(part);
    if (bear) {
      const from = Number(bear[1]);
      if (!Number.isInteger(from) || from < 1 || from > 24) return null;
      steps.push({ from, to: "off" });
      continue;
    }
    const hop = /^(\d+)→(\d+)$/.exec(part);
    if (!hop) return null;
    const from = Number(hop[1]);
    const to = Number(hop[2]);
    if (!Number.isInteger(from) || !Number.isInteger(to) || from < 1 || from > 24 || to < 1 || to > 24) return null;
    steps.push({ from, to });
  }
  return steps.length ? steps : null;
}

function sameStep(a: Step, b: Step): boolean {
  return a.from === b.from && a.to === b.to;
}

function applyPrefix(
  points: NardyPoint[],
  side: Side,
  prefix: Step[],
  whiteOff: number,
  blackOff: number,
): { points: NardyPoint[]; whiteOff: number; blackOff: number } {
  const map = new Map<number, NardyPoint>();
  for (let point = 1; point <= 24; point += 1) {
    const found = points.find((item) => item.point === point);
    map.set(point, { point, white: found?.white ?? 0, black: found?.black ?? 0 });
  }
  let white = whiteOff;
  let black = blackOff;
  for (const step of prefix) {
    const src = map.get(step.from);
    if (!src || src[side] <= 0) break;
    src[side] -= 1;
    if (step.to === "off") {
      if (side === "white") white += 1;
      else black += 1;
    } else {
      const dst = map.get(step.to);
      if (!dst) break;
      dst[side] += 1;
    }
  }
  return { points: Array.from(map.values()), whiteOff: white, blackOff: black };
}

function Checkers({ count, tone, toward }: { count: number; tone: Side; toward: "down" | "up" }) {
  if (count <= 0) return null;
  const shown = Math.min(count, 5);
  return (
    <span className={`nardy-checkers is-${toward}`}>
      {Array.from({ length: shown }, (_, index) => {
        const outer = index === shown - 1;
        return (
          <span
            key={index}
            className={`nardy-pip is-${tone}`}
            data-top={outer ? "1" : undefined}
            style={{ ["--i" as string]: index, zIndex: index + 1 }}
          >
            {outer && count > shown ? <span className="nardy-count">{count}</span> : null}
          </span>
        );
      })}
    </span>
  );
}

function PointCell({
  point,
  stack,
  interactive,
  selected,
  source,
  dest,
  onPoint,
}: {
  point: number;
  stack: NardyPoint;
  interactive: boolean;
  selected: boolean;
  source: boolean;
  dest: boolean;
  onPoint: (point: number) => void;
}) {
  const top = point >= 13;
  const className = [
    "nardy-point",
    top ? "is-top" : "is-bottom",
    isDarkPoint(point) ? "is-dark" : "is-light",
    isHome(point) ? "is-home" : "",
    selected ? "is-selected" : "",
    source ? "is-source" : "",
    dest ? "is-dest" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const pieces = [
    stack.white > 0 ? `белых ${stack.white}` : "",
    stack.black > 0 ? `чёрных ${stack.black}` : "",
  ]
    .filter(Boolean)
    .join(", ");
  const action = dest ? ", можно поставить" : source ? ", можно выбрать" : "";
  const label = `Пункт ${point}${pieces ? `, ${pieces}` : ""}${action}`;
  const body = (
    <>
      <span className="nardy-tri" />
      <Checkers count={stack.white} tone="white" toward={top ? "down" : "up"} />
      <Checkers count={stack.black} tone="black" toward={top ? "down" : "up"} />
      <span className="nardy-point-no">{point}</span>
    </>
  );
  if (!interactive) {
    return (
      <div className={className} data-nardy-point={point}>
        {body}
      </div>
    );
  }
  return (
    <button
      type="button"
      className={className}
      data-nardy-point={point}
      aria-label={label}
      aria-pressed={selected || undefined}
      onClick={() => onPoint(point)}
    >
      {body}
    </button>
  );
}

function TrayStack({ count, tone, toward }: { count: number; tone: Side; toward: "down" | "up" }) {
  if (count <= 0) return null;
  const shown = Math.min(count, 5);
  return (
    <span className="nardy-tray-stack" style={{ ["--n" as string]: shown }}>
      {Array.from({ length: shown }, (_, index) => (
        <span key={index} className={`nardy-pip is-${tone} is-${toward}`} style={{ ["--i" as string]: index }}>
          {index === shown - 1 && count > shown ? <span className="nardy-count">{count}</span> : null}
        </span>
      ))}
    </span>
  );
}

function OffTray({
  tone,
  count,
  interactive,
  dest,
  onBear,
}: {
  tone: Side;
  count: number;
  interactive: boolean;
  dest: boolean;
  onBear: () => void;
}) {
  const className = `nardy-tray is-${tone}${dest ? " is-dest" : ""}`;
  const name = tone === "white" ? "Белые" : "Чёрные";
  const body = (
    <>
      <TrayStack count={count} tone={tone} toward={tone === "white" ? "up" : "down"} />
      <span className="nardy-tray-label">{name}</span>
    </>
  );
  if (interactive && dest) {
    return (
      <button type="button" className={className} data-nardy-off={tone} aria-label={`Снять в лоток ${name}, уже ${count}`} onClick={onBear}>
        {body}
      </button>
    );
  }
  return (
    <div className={className} data-nardy-off={tone} aria-label={`Снято ${name}: ${count}`}>
      {body}
    </div>
  );
}

function DieFace({ value }: { value: number }) {
  const on = new Set(DIE_PIPS[value] ?? []);
  return (
    <span className="nardy-die" aria-hidden="true">
      {Array.from({ length: 9 }, (_, index) => (
        <span key={index} className={on.has(index) ? "nardy-dot" : "nardy-dot is-off"} />
      ))}
    </span>
  );
}

function DiceWell({ dice }: { dice: number[] }) {
  const doubles = dice.length === 2 && dice[0] === dice[1];
  const faces = doubles ? [dice[0], dice[0], dice[1], dice[1]] : dice;
  const label = doubles ? `Дубль ${dice[0]}, четыре хода` : `Кости ${dice.join(" и ")}`;
  return (
    <div className={`nardy-dice-well${doubles ? " is-double" : ""}`} aria-label={label}>
      {faces.map((value, index) => (
        <DieFace key={`${value}-${index}`} value={value} />
      ))}
    </div>
  );
}

function Half({
  points,
  top,
  bottom,
  interactive,
  selected,
  sources,
  dests,
  onPoint,
}: {
  points: NardyPoint[];
  top: number[];
  bottom: number[];
  interactive: boolean;
  selected: number | null;
  sources: ReadonlySet<number>;
  dests: ReadonlySet<number>;
  onPoint: (point: number) => void;
}) {
  const cell = (point: number) => {
    const stack = pointOf(points, point);
    return (
      <PointCell
        key={point}
        point={point}
        stack={stack}
        interactive={interactive}
        selected={selected === point}
        source={sources.has(point)}
        dest={dests.has(point)}
        onPoint={onPoint}
      />
    );
  };
  return (
    <div className="nardy-half">
      <div className="nardy-points is-top">{top.map(cell)}</div>
      <div className="nardy-gutter" />
      <div className="nardy-points is-bottom">{bottom.map(cell)}</div>
    </div>
  );
}

export function NardyBoard({
  points,
  whiteOff = 0,
  blackOff = 0,
  dice = null,
  interactive = false,
  side = null,
  selected = null,
  sources,
  dests,
  bearOff = false,
  onPoint,
  onBear,
}: {
  points: NardyPoint[];
  whiteOff?: number;
  blackOff?: number;
  dice?: number[] | null;
  interactive?: boolean;
  side?: Side | null;
  selected?: number | null;
  sources?: ReadonlySet<number>;
  dests?: ReadonlySet<number>;
  bearOff?: boolean;
  onPoint?: (point: number) => void;
  onBear?: () => void;
}) {
  const sourceSet = sources ?? new Set<number>();
  const destSet = dests ?? new Set<number>();
  const pick = onPoint ?? (() => undefined);
  const bear = onBear ?? (() => undefined);
  return (
    <div className="nardy-stage">
    <div className="nardy-board" data-nardy-board="" role="group" aria-label="Стол длинных нард">
      <OffTray tone="black" count={blackOff} interactive={interactive} dest={bearOff && side === "black"} onBear={bear} />
      <div className="nardy-field">
        <Half
          points={points}
          top={LEFT_TOP}
          bottom={LEFT_BOTTOM}
          interactive={interactive}
          selected={selected}
          sources={sourceSet}
          dests={destSet}
          onPoint={pick}
        />
        <div className="nardy-bar" />
        <Half
          points={points}
          top={RIGHT_TOP}
          bottom={RIGHT_BOTTOM}
          interactive={interactive}
          selected={selected}
          sources={sourceSet}
          dests={destSet}
          onPoint={pick}
        />
        {dice && dice.length > 0 ? (
          <DiceWell dice={dice} />
        ) : null}
      </div>
      <OffTray tone="white" count={whiteOff} interactive={interactive} dest={bearOff && side === "white"} onBear={bear} />
    </div>
    <p className="nardy-legend">
      <span><i className="nardy-swatch is-white" /> Белые с пункта 24, сверху справа</span>
      <span><i className="nardy-swatch is-black" /> Чёрные с пункта 12, снизу слева</span>
      <span>Цифра на шашке — сколько их на пункте</span>
    </p>
    </div>
  );
}

export function CasinoNardyTable() {
  const { tableId = "" } = useParams();
  const { isAuthed } = useSession();
  const [snap, setSnap] = useState<NardySnapshot | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [armResign, setArmResign] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [prefix, setPrefix] = useState<Step[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const ticket = useRef(0);

  async function load() {
    const mine = ++ticket.current;
    try {
      const next = isAuthed ? await getNardyTable(tableId) : await getNardyWatch(tableId);
      if (mine !== ticket.current) return;
      setSnap(next);
      setError("");
    } catch (err) {
      if (mine !== ticket.current) return;
      setError(err instanceof Error ? err.message : "Стол не открылся");
    }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 2000);
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(clock);
    };
  }, [tableId, isAuthed]);

  const mine = snap?.your_side ?? null;
  const myTurn = Boolean(snap && mine && snap.turn === mine && snap.status === "running");
  const diceKey = (snap?.dice ?? []).join(",");
  const legalKey = (snap?.legal ?? []).map((move) => `${move.index}:${move.label}`).join("|");

  useEffect(() => {
    setPrefix([]);
    if (!myTurn) {
      setSelected(null);
      return;
    }
    const sources = new Set<number>();
    for (const part of legalKey.split("|")) {
      if (!part) continue;
      const steps = parseLabel(part.slice(part.indexOf(":") + 1));
      if (steps && steps[0]) sources.add(steps[0].from);
    }
    setSelected(sources.size === 1 ? ([...sources][0] ?? null) : null);
  }, [tableId, snap?.state_version, diceKey, legalKey, myTurn]);

  async function run(task: () => Promise<NardySnapshot>) {
    const mine = ++ticket.current;
    setBusy(true);
    setError("");
    try {
      const next = await task();
      if (mine !== ticket.current) return;
      setSnap(next);
      setArmResign(false);
      setPrefix([]);
      setSelected(null);
    } catch (err) {
      if (mine !== ticket.current) return;
      setError(err instanceof Error ? err.message : "Не вышло");
      setBusy(false);
      await load();
    } finally {
      if (mine === ticket.current) setBusy(false);
    }
  }

  const playable = (snap?.legal ?? []).flatMap((move) => {
    const steps = parseLabel(move.label);
    if (!steps || steps.length === 0) return [];
    return [{ index: move.index, label: move.label, steps }];
  });
  const burned = (snap?.legal ?? []).filter((move) => {
    const steps = parseLabel(move.label);
    return steps != null && steps.length === 0;
  });
  const unread = (snap?.legal ?? []).filter((move) => parseLabel(move.label) == null);

  function matching(stepsPrefix: Step[]) {
    return playable.filter(
      (move) => move.steps.length >= stepsPrefix.length && stepsPrefix.every((step, index) => sameStep(step, move.steps[index])),
    );
  }

  const viable = matching(prefix);
  const upcoming = viable.flatMap((move) => {
    const step = move.steps[prefix.length];
    return step ? [step] : [];
  });
  const sourceSet = new Set(upcoming.map((step) => step.from));
  const destSet = new Set(
    upcoming.filter((step) => step.from === selected && typeof step.to === "number").map((step) => step.to as number),
  );
  const bearOff = selected != null && upcoming.some((step) => step.from === selected && step.to === "off");
  const view =
    snap && mine ? applyPrefix(snap.points, mine, prefix, snap.white_off, snap.black_off) : null;

  function play(index: number) {
    if (!snap || busy) return;
    setPrefix([]);
    setSelected(null);
    void run(() => actNardyTable(tableId, { move_index: index, expected_version: snap.state_version }));
  }

  function commitStep(step: Step) {
    const nextPrefix = [...prefix, step];
    const left = matching(nextPrefix);
    const longer = left.filter((move) => move.steps.length > nextPrefix.length);
    const complete = left.filter((move) => move.steps.length === nextPrefix.length);
    if (longer.length === 0 && complete.length > 0) {
      play(complete[0].index);
      return;
    }
    if (longer.length === 0) return;
    setPrefix(nextPrefix);
    const sources = new Set(
      longer.map((move) => move.steps[nextPrefix.length]?.from).filter((item): item is number => typeof item === "number"),
    );
    setSelected(sources.size === 1 ? ([...sources][0] ?? null) : null);
  }

  function onPoint(point: number) {
    if (!snap || busy || !myTurn || !mine || !view) return;
    if (selected != null && upcoming.some((step) => step.from === selected && step.to === point)) {
      commitStep({ from: selected, to: point });
      return;
    }
    if (upcoming.some((step) => step.from === point)) {
      setSelected(point);
      return;
    }
    const shown = view.points.find((item) => item.point === point);
    if (!shown || shown[mine] <= 0) return;
    setPrefix([]);
    if (playable.some((move) => move.steps[0]?.from === point)) {
      setSelected(point);
      return;
    }
    const sources = new Set(playable.map((move) => move.steps[0].from));
    setSelected(sources.size === 1 ? ([...sources][0] ?? null) : null);
  }

  function onBear() {
    if (selected == null || !upcoming.some((step) => step.from === selected && step.to === "off")) return;
    commitStep({ from: selected, to: "off" });
  }

  function restartPick() {
    setPrefix([]);
    const sources = new Set(playable.map((move) => move.steps[0].from));
    setSelected(sources.size === 1 ? ([...sources][0] ?? null) : null);
  }

  const leftSeconds =
    snap?.deadline_at && snap.status === "running"
      ? Math.max(0, Math.ceil((new Date(snap.deadline_at).getTime() - now) / 1000))
      : null;

  const turnLine = myTurn ? "Ваш ход" : snap?.turn ? `Ход ${sideName(snap.turn)}` : snap?.status === "waiting" ? "Ждём соперника" : "";

  return (
    <div className="casino-play" data-casino-nardy="table">
      <p className="casino-muted">
        <Link to={casinoTo("/casino/play/nardy")}>← К столам</Link>
      </p>
      <h1>Длинные нарды</h1>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {snap ? (
        <>
          <p className="nardy-status">
            <span>{mine ? `Вы — ${sideName(mine)}` : "Вы наблюдаете"}</span>
            {turnLine ? <span className={myTurn ? "nardy-turn is-you" : "nardy-turn"}>{turnLine}</span> : null}
            <span>Ставка {formatRub(snap.stake_rub)}</span>
          </p>
          {leftSeconds != null && myTurn ? <p className="casino-muted">Ход ещё {leftSeconds} с, потом сдача.</p> : null}
          <NardyBoard
            points={view?.points ?? snap.points}
            whiteOff={view?.whiteOff ?? snap.white_off}
            blackOff={view?.blackOff ?? snap.black_off}
            dice={snap.dice}
            interactive={myTurn && !busy}
            side={mine}
            selected={myTurn ? selected : null}
            sources={myTurn ? sourceSet : undefined}
            dests={myTurn ? destSet : undefined}
            bearOff={myTurn && bearOff}
            onPoint={onPoint}
            onBear={onBear}
          />
          {myTurn ? (
            <div className="nardy-hint">
              <p className="casino-muted">
                {playable.length === 0
                  ? "Ходить некуда."
                  : bearOff || destSet.size > 0
                    ? "Нажмите подсвеченный пункт."
                    : "Нажмите свою шашку."}
              </p>
              {prefix.length > 0 ? (
                <button type="button" className="nardy-text-btn" onClick={restartPick}>
                  Заново
                </button>
              ) : null}
            </div>
          ) : null}
          {snap.result ? (
            <p>
              <strong>
                {snap.result.kind === "mars" ? "Марс" : "Ойн"}. Победили {sideName(snap.result.winner)}.
                {mine ? (snap.result.you_won ? " Вы выиграли." : " Вы проиграли.") : ""}
              </strong>
            </p>
          ) : null}
          {snap.start_white && snap.start_black ? (
            <p className="casino-muted">
              Первый зар: белые {snap.start_white}, чёрные {snap.start_black}.
            </p>
          ) : null}
          {mine ? <p className="casino-muted">Со счёта списано {formatRub(snap.lock_rub)}.</p> : null}
          {snap.status === "waiting" && mine === "white" ? <p>Ждём чёрных. Отмена вернёт обе ставки.</p> : null}
          {myTurn && playable.length === 0 && burned.length > 0 ? (
            <button type="button" className="casino-btn" disabled={busy} onClick={() => play(burned[0].index)}>
              Ход сгорел
            </button>
          ) : null}
          {myTurn && unread.length > 0 ? (
            <div className="nardy-moves">
              {unread.map((move) => (
                <button key={move.index} type="button" className="casino-btn" disabled={busy} onClick={() => play(move.index)}>
                  {move.label}
                </button>
              ))}
            </div>
          ) : null}
          {snap.status === "running" && mine && !myTurn ? <p className="casino-muted">Ход соперника.</p> : null}
          {mine && (snap.status === "waiting" || snap.status === "running") ? (
            <p>
              {armResign ? (
                <button type="button" className="casino-btn" disabled={busy} onClick={() => void run(() => leaveNardyTable(tableId))}>
                  {snap.status === "waiting" ? "Да, отменить стол" : "Да, сдаться"}
                </button>
              ) : (
                <button type="button" className="casino-btn" disabled={busy} onClick={() => setArmResign(true)}>
                  {snap.status === "waiting" ? "Отменить стол" : "Сдаться"}
                </button>
              )}
            </p>
          ) : null}
          <p className="casino-muted">
            Проверка: {snap.commit.slice(0, 16)}…
            {snap.server_seed ? ` Сид ${snap.server_seed}` : " Сид откроется после партии."}
          </p>
        </>
      ) : error ? null : (
        <p className="casino-muted">Открываю стол…</p>
      )}
    </div>
  );
}
