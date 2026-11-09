import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import {
  verifyCasinoFairness,
  type CasinoFairnessGame,
  type CasinoFairnessSide,
  type CasinoFairnessVerifyResponse,
} from "@/lib/public";
import { casinoTo } from "@/casino/casinoPaths";
import { isShelvedCasinoGame } from "@/casino/gameCatalog";

const GAME_TYPES: { id: CasinoFairnessGame; label: string }[] = [
  { id: "baccara", label: "Баккара" },
  { id: "blackjack", label: "Блэкджек" },
  { id: "roulette", label: "Рулетка" },
  { id: "holdem", label: "Холдем" },
  { id: "jackpot", label: "Джекпот" },
  { id: "fixed_room", label: "Комнаты" },
  { id: "raffle", label: "FocusLucky" },
  { id: "clan_war", label: "Клан vs клан" },
];

const SIDES: { id: CasinoFairnessSide; label: string }[] = [
  { id: "creator", label: "Создатель" },
  { id: "opponent", label: "Соперник" },
  { id: "seat1", label: "Место 1" },
  { id: "seat2", label: "Место 2" },
  { id: "seat3", label: "Место 3" },
  { id: "seat4", label: "Место 4" },
  { id: "seat5", label: "Место 5" },
  { id: "seat6", label: "Место 6" },
];

function parseSide(raw: string): CasinoFairnessSide | "" {
  return SIDES.some((item) => item.id === raw) ? (raw as CasinoFairnessSide) : "";
}

function firstParam(params: URLSearchParams, key: string): string {
  return (params.get(key) || "").trim();
}

function parseCards(raw: string): string[] | undefined {
  const cards = raw
    .split(/[\s,]+/)
    .map((card) => card.trim())
    .filter(Boolean);
  return cards.length ? cards : undefined;
}

function parseGame(raw: string): CasinoFairnessGame {
  if (
    raw === "blackjack" ||
    raw === "holdem" ||
    raw === "jackpot" ||
    raw === "raffle" ||
    raw === "fixed_room" ||
    raw === "clan_war" ||
    raw === "roulette"
  ) {
    return raw;
  }
  return "baccara";
}

function isHmacGame(game: CasinoFairnessGame): boolean {
  return game === "fixed_room" || game === "clan_war";
}

function autoVerifyFromParams(params: URLSearchParams): {
  game_type: CasinoFairnessGame;
  game_id: string;
  commit: string;
  server_seed: string;
  client_seed: string;
  nonce: number;
  side?: CasinoFairnessSide;
  expected_cards?: string[];
  total_tickets?: number;
  expected_ticket?: number;
  hmac_message?: string;
  modulus?: number;
  expected_index?: number;
  expected_pocket?: number;
} | null {
  const game_id = firstParam(params, "game_id");
  const commit = firstParam(params, "commit");
  const server_seed = firstParam(params, "server_seed");
  const client_seed = firstParam(params, "client_seed") || "focuspay";
  const nonce = Number.parseInt(firstParam(params, "nonce") || "0", 10);
  const game_type = parseGame(firstParam(params, "game_type"));
  if (!game_id || !commit || !server_seed) {
    return null;
  }
  if (game_type === "jackpot" || game_type === "raffle") {
    const total_tickets = Number.parseInt(firstParam(params, "total_tickets") || "0", 10);
    if (!Number.isFinite(total_tickets) || total_tickets < 1) return null;
    const ticketRaw = firstParam(params, "expected_ticket");
    const expected_ticket = ticketRaw ? Number.parseInt(ticketRaw, 10) : undefined;
    return {
      game_type,
      game_id,
      commit,
      server_seed,
      client_seed,
      nonce: game_type === "raffle" && Number.isFinite(nonce) ? nonce : 0,
      total_tickets,
      expected_ticket: expected_ticket != null && Number.isFinite(expected_ticket) ? expected_ticket : undefined,
    };
  }
  if (isHmacGame(game_type)) {
    const hmac_message = firstParam(params, "hmac_message");
    const modulus = Number.parseInt(firstParam(params, "modulus") || "0", 10);
    if (!hmac_message || !Number.isFinite(modulus) || modulus < 2) return null;
    const indexRaw = firstParam(params, "expected_index");
    const expected_index = indexRaw ? Number.parseInt(indexRaw, 10) : undefined;
    return {
      game_type,
      game_id,
      commit,
      server_seed,
      client_seed,
      nonce: 0,
      hmac_message,
      modulus,
      expected_index: expected_index != null && Number.isFinite(expected_index) ? expected_index : undefined,
    };
  }
  if (!Number.isFinite(nonce) || nonce < 0) {
    return null;
  }
  if (game_type === "roulette") {
    const pocketRaw = firstParam(params, "expected_pocket");
    const expected_pocket = pocketRaw ? Number.parseInt(pocketRaw, 10) : undefined;
    return {
      game_type,
      game_id,
      commit,
      server_seed,
      client_seed,
      nonce,
      expected_pocket:
        expected_pocket != null && Number.isFinite(expected_pocket) ? expected_pocket : undefined,
    };
  }
  const side = parseSide(firstParam(params, "side"));
  const expected_cards = parseCards(firstParam(params, "expected_cards"));
  if (expected_cards && !side && game_type !== "holdem") {
    return null;
  }
  return {
    game_type,
    game_id,
    commit,
    server_seed,
    client_seed,
    nonce,
    side: side || undefined,
    expected_cards,
  };
}

export function CasinoFairness() {
  const [params] = useSearchParams();
  const [gameType, setGameType] = useState<CasinoFairnessGame>(parseGame(firstParam(params, "game_type")));
  const [gameId, setGameId] = useState(firstParam(params, "game_id"));
  const [commit, setCommit] = useState(firstParam(params, "commit"));
  const [serverSeed, setServerSeed] = useState(firstParam(params, "server_seed"));
  const [clientSeed, setClientSeed] = useState(firstParam(params, "client_seed") || "focuspay");
  const [nonce, setNonce] = useState(firstParam(params, "nonce") || "0");
  const [side, setSide] = useState<CasinoFairnessSide | "">(parseSide(firstParam(params, "side")));
  const [expectedCards, setExpectedCards] = useState(firstParam(params, "expected_cards"));
  const [totalTickets, setTotalTickets] = useState(firstParam(params, "total_tickets"));
  const [expectedTicket, setExpectedTicket] = useState(firstParam(params, "expected_ticket"));
  const [hmacMessage, setHmacMessage] = useState(firstParam(params, "hmac_message"));
  const [modulus, setModulus] = useState(firstParam(params, "modulus"));
  const [expectedIndex, setExpectedIndex] = useState(firstParam(params, "expected_index"));
  const [expectedPocket, setExpectedPocket] = useState(firstParam(params, "expected_pocket"));
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<CasinoFairnessVerifyResponse | null>(null);

  const nonceNumber = useMemo(() => Number.parseInt(nonce, 10), [nonce]);
  const query = params.toString();
  const autoPayload = useMemo(() => autoVerifyFromParams(new URLSearchParams(query)), [query]);

  useEffect(() => {
    if (!autoPayload) {
      return;
    }
    let cancelled = false;
    setPending(true);
    setResult(null);
    verifyCasinoFairness(autoPayload)
      .then((response) => {
        if (!cancelled) {
          setResult(response);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          toast.error(error instanceof ApiError ? error.message : "Не удалось проверить раунд");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setPending(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [autoPayload]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (gameType === "jackpot" || gameType === "raffle") {
      const tickets = Number.parseInt(totalTickets, 10);
      if (!Number.isFinite(tickets) || tickets < 1) {
        toast.error("Укажите число билетов");
        return;
      }
      setPending(true);
      setResult(null);
      try {
        const ticketRaw = expectedTicket.trim();
        const response = await verifyCasinoFairness({
          game_type: gameType,
          game_id: gameId.trim(),
          server_seed: serverSeed.trim(),
          client_seed: clientSeed.trim() || "focuspay",
          nonce: gameType === "raffle" ? Number.parseInt(nonce, 10) || 1 : 0,
          commit: commit.trim(),
          total_tickets: tickets,
          expected_ticket: ticketRaw ? Number.parseInt(ticketRaw, 10) : undefined,
        });
        setResult(response);
      } catch (error) {
        toast.error(error instanceof ApiError ? error.message : "Не удалось проверить раунд");
      } finally {
        setPending(false);
      }
      return;
    }
    if (isHmacGame(gameType)) {
      const n = Number.parseInt(modulus, 10);
      if (!hmacMessage.trim() || !Number.isFinite(n) || n < 2) {
        toast.error("Укажите HMAC-сообщение и модуль (N мест или 2 клана)");
        return;
      }
      setPending(true);
      setResult(null);
      try {
        const indexRaw = expectedIndex.trim();
        const response = await verifyCasinoFairness({
          game_type: gameType,
          game_id: gameId.trim(),
          server_seed: serverSeed.trim(),
          client_seed: clientSeed.trim() || "focuspay",
          nonce: 0,
          commit: commit.trim(),
          hmac_message: hmacMessage.trim(),
          modulus: n,
          expected_index: indexRaw ? Number.parseInt(indexRaw, 10) : undefined,
        });
        setResult(response);
      } catch (error) {
        toast.error(error instanceof ApiError ? error.message : "Не удалось проверить раунд");
      } finally {
        setPending(false);
      }
      return;
    }
    if (!Number.isFinite(nonceNumber) || nonceNumber < 0) {
      toast.error("Nonce должен быть целым числом ≥ 0");
      return;
    }
    if (gameType === "roulette") {
      const pocketRaw = expectedPocket.trim();
      const pocket = pocketRaw ? Number.parseInt(pocketRaw, 10) : undefined;
      if (pocket != null && (!Number.isFinite(pocket) || pocket < 0 || pocket > 36)) {
        toast.error("Лунка — целое число от 0 до 36");
        return;
      }
      setPending(true);
      setResult(null);
      try {
        const response = await verifyCasinoFairness({
          game_type: "roulette",
          game_id: gameId.trim(),
          server_seed: serverSeed.trim(),
          client_seed: clientSeed.trim() || "focuspay",
          nonce: nonceNumber,
          commit: commit.trim(),
          expected_pocket: pocket,
        });
        setResult(response);
      } catch (error) {
        toast.error(error instanceof ApiError ? error.message : "Не удалось проверить раунд");
      } finally {
        setPending(false);
      }
      return;
    }
    const cards = parseCards(expectedCards);
    if (cards && !side && gameType !== "holdem") {
      toast.error("Чтобы сверить карты, укажите сторону: создатель, соперник или место 1–6");
      return;
    }
    setPending(true);
    setResult(null);
    try {
      const response = await verifyCasinoFairness({
        game_type: gameType,
        game_id: gameId.trim(),
        server_seed: serverSeed.trim(),
        client_seed: clientSeed.trim(),
        nonce: nonceNumber,
        commit: commit.trim(),
        side: side || undefined,
        expected_cards: cards,
      });
      setResult(response);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось проверить раунд");
    } finally {
      setPending(false);
    }
  }

  const commitLabel =
    gameType === "jackpot"
      ? "Хеш roll до ставок"
      : gameType === "raffle"
        ? "Хеш seed до шоу"
        : isHmacGame(gameType)
        ? "Commit SHA-256(seed)"
        : gameType === "roulette"
          ? "Хеш сида до спина"
          : "Хеш колоды до раунда";
  const seedLabel =
    gameType === "jackpot"
      ? "Roll после спина"
      : gameType === "raffle"
        ? "Seed после шоу"
        : isHmacGame(gameType)
        ? "Серверный сид после розыгрыша"
        : gameType === "roulette"
          ? "Серверный сид после спина"
          : "Серверный сид после раунда";

  return (
    <div className="casino-fairness" data-casino-fairness="">
      <nav className="casino-crumb" aria-label="Навигация">
        <Link to={casinoTo("/casino")}>Лобби</Link>
        <span className="casino-crumb-sep" aria-hidden>
          /
        </span>
        <span>Честность</span>
      </nav>
      <p className="casino-play-kicker">HMAC</p>
      <h1>Проверка честности</h1>
      <p className="casino-muted">
        Карты: хеш до сдачи, сид после. Джекпот: SHA-256(roll) до ставок. FocusLucky: HMAC-SHA256(seed, place) по модулю оставшихся билетов, сид после шоу.
      </p>

      <section className="casino-fairness-card">
        <h2>Как это считается</h2>
        <p className="casino-muted">Тот же алгоритм, что использует сервер при раздаче.</p>
        <ol className="casino-fairness-steps">
          <li>
            До ставки сервер показывает хеш раунда:{" "}
            <code className="casino-mono">SHA-256(серверный_сид:номер_игры)</code>. Сам сид ещё скрыт.
          </li>
          <li>
            Колода тасуется так:{" "}
            <code className="casino-mono">
              HMAC-SHA256(серверный_сид, "клиентский_сид:nonce:номер_игры:сторона:позиция")
            </code>
            . Карты снимаются с конца перемешанной колоды.
          </li>
          <li>
            После раунда сервер открывает сид. Подставьте его сюда вместе с хешем, который видели до игры. Совпало —
            колода та же. Испортите в сиде один символ — проверка обязана сказать «не сходится».
          </li>
        </ol>
        <p className="casino-muted">
          Джекпот: сервер сразу показывает SHA-256(roll). После закрытия ставок winning_ticket = floor(roll ×
          total_tickets). Подставить roll и хеш сюда. Кубики в чате — броски Telegram, их здесь проверять нельзя.
        </p>
        <p className="casino-muted">
          Рулетка: лунка ={" "}
          <code className="casino-mono">
            HMAC-SHA256(серверный_сид, "клиентский_сид:nonce:номер_игры:pocket") mod 37
          </code>
          . Цвет и выплата берутся из правил колеса 0–36, сервер их не подкручивает.
        </p>
      </section>

      <section className="casino-fairness-card">
        <h2>Проверить раунд</h2>
        <p className="casino-muted">
          По ссылке из бота проверка запускается сама. Можно испортить сид и нажать ещё раз.
        </p>
        <form onSubmit={submit} className="casino-fairness-form">
          <label className="casino-field">
            Игра
            <select id="game_type" value={gameType} onChange={(event) => setGameType(event.target.value as CasinoFairnessGame)}>
              {GAME_TYPES.filter((item) => !isShelvedCasinoGame(item.id) || item.id === gameType).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="casino-field">
            Номер игры
            <input id="game_id" className="casino-mono" value={gameId} onChange={(event) => setGameId(event.target.value)} required />
          </label>
          <label className="casino-field">
            {commitLabel}
            <input id="commit" className="casino-mono" value={commit} onChange={(event) => setCommit(event.target.value)} required />
          </label>
          <label className="casino-field">
            {seedLabel}
            <input
              id="server_seed"
              className="casino-mono"
              value={serverSeed}
              onChange={(event) => setServerSeed(event.target.value)}
              required
            />
          </label>
          {isHmacGame(gameType) ? (
            <>
              <label className="casino-field">
                Сообщение HMAC (порядок мест / кланы)
                <input
                  id="hmac_message"
                  className="casino-mono"
                  value={hmacMessage}
                  onChange={(event) => setHmacMessage(event.target.value)}
                  required
                />
              </label>
              <div className="casino-fairness-row">
                <label className="casino-field">
                  {gameType === "clan_war" ? "Модуль (2 клана)" : "Модуль (N мест)"}
                  <input
                    id="modulus"
                    className="casino-mono"
                    inputMode="numeric"
                    value={modulus}
                    onChange={(event) => setModulus(event.target.value)}
                    required
                  />
                </label>
                <label className="casino-field">
                  Индекс победителя (необязательно)
                  <input
                    id="expected_index"
                    className="casino-mono"
                    inputMode="numeric"
                    value={expectedIndex}
                    onChange={(event) => setExpectedIndex(event.target.value)}
                  />
                </label>
              </div>
            </>
          ) : gameType === "jackpot" || gameType === "raffle" ? (
            <div className="casino-fairness-row">
              {gameType === "raffle" ? (
                <label className="casino-field">
                  Место (nonce)
                  <input
                    id="nonce"
                    className="casino-mono"
                    inputMode="numeric"
                    value={nonce}
                    onChange={(event) => setNonce(event.target.value)}
                    required
                  />
                </label>
              ) : null}
              <label className="casino-field">
                Всего билетов
                <input
                  id="total_tickets"
                  className="casino-mono"
                  inputMode="numeric"
                  value={totalTickets}
                  onChange={(event) => setTotalTickets(event.target.value)}
                  required
                />
              </label>
              <label className="casino-field">
                Выигрышный билет (необязательно)
                <input
                  id="expected_ticket"
                  className="casino-mono"
                  inputMode="numeric"
                  value={expectedTicket}
                  onChange={(event) => setExpectedTicket(event.target.value)}
                />
              </label>
            </div>
          ) : (
            <>
              <div className="casino-fairness-row">
                <label className="casino-field">
                  Клиентский сид
                  <input
                    id="client_seed"
                    className="casino-mono"
                    value={clientSeed}
                    onChange={(event) => setClientSeed(event.target.value)}
                    required
                  />
                </label>
                <label className="casino-field">
                  Nonce
                  <input
                    id="nonce"
                    className="casino-mono"
                    inputMode="numeric"
                    value={nonce}
                    onChange={(event) => setNonce(event.target.value)}
                    required
                  />
                </label>
              </div>
              {gameType === "roulette" ? (
                <label className="casino-field">
                  Лунка 0–36 (необязательно)
                  <input
                    id="expected_pocket"
                    className="casino-mono"
                    inputMode="numeric"
                    value={expectedPocket}
                    onChange={(event) => setExpectedPocket(event.target.value)}
                    placeholder="23"
                  />
                </label>
              ) : gameType !== "holdem" ? (
                <label className="casino-field">
                  Сторона (если сверяете карты)
                  <select
                    id="side"
                    value={side || "none"}
                    onChange={(event) => setSide(event.target.value === "none" ? "" : (event.target.value as CasinoFairnessSide))}
                  >
                    <option value="none">Не сверять карты</option>
                    {SIDES.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              {gameType === "roulette" ? null : (
                <label className="casino-field">
                  {gameType === "holdem" ? "Борд (необязательно)" : "Карты (необязательно)"}
                  <textarea
                    id="expected_cards"
                    className="casino-mono"
                    value={expectedCards}
                    onChange={(event) => setExpectedCards(event.target.value)}
                    placeholder="A♠ 9♥"
                    rows={2}
                  />
                </label>
              )}
            </>
          )}
          <button type="submit" className="casino-btn casino-bet-btn" disabled={pending}>
            {pending ? "Проверяю…" : "Проверить"}
          </button>
        </form>
      </section>

      {result ? (
        <section
          className={`casino-fairness-card casino-fairness-result${result.matches ? " is-match" : " is-miss"}`}
          data-casino-fairness-result={result.matches ? "match" : "mismatch"}
        >
          <h2>{result.matches ? "Сходится" : "Не сходится"}</h2>
          <p className="casino-muted">
            {result.matches
              ? "Открытый сид даёт тот же хеш, который был показан до карт."
              : "Хеш от этого сида не совпадает с хешем раунда. Если вы испортили один символ — так и должно быть."}
          </p>
          <p className="casino-mono casino-fairness-hash">
            <span>Алгоритм:</span> {result.algorithm}
          </p>
          <p className="casino-mono casino-fairness-hash">
            <span>Хеш из формы:</span> {commit}
          </p>
          <p className="casino-mono casino-fairness-hash">
            <span>Хеш от сида:</span> {result.computed_commit}
          </p>
          {result.pocket != null ? (
            <p className="casino-mono casino-fairness-hash">
              <span>Лунка:</span> {result.pocket} / 37{result.color ? ` · ${result.color}` : ""}
            </p>
          ) : null}
          {result.winning_ticket != null ? (
            <p className="casino-mono casino-fairness-hash">
              <span>Билет:</span> {result.winning_ticket}
              {result.total_tickets != null ? ` / ${result.total_tickets}` : ""}
            </p>
          ) : null}
          {Object.entries(result.cards || {}).map(([key, cards]) => (
            <p key={key} className="casino-mono casino-fairness-hash">
              <span>{key}:</span> {(cards || []).join(" ")}
            </p>
          ))}
        </section>
      ) : null}
    </div>
  );
}
