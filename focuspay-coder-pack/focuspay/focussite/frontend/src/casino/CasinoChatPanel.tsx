import { useEffect, useMemo, useRef, useState } from "react";
import { MessageCircle, Send, Swords, Users, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { ApiError, API_BASE, getToken } from "@/lib/api";
import {
  getCasinoChatDm,
  getCasinoChatDms,
  getCasinoChatLobby,
  joinCasinoDuel,
  postCasinoChatChallenge,
  postCasinoChatDm,
  postCasinoChatLobby,
  type CasinoChatActor,
  type CasinoChatMessage,
  type CasinoChatThread,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CasinoPlayerAvatar } from "./CasinoPlayerChip";
import { CASINO_CATALOG } from "./gameCatalog";

const DUEL_GAMES = CASINO_CATALOG.filter(
  (game) => game.id === "pvp_dice" || game.id === "baccara" || game.id === "blackjack",
);

type Tab = "lobby" | "dms";

/** Overlay uses `open`; a docked rail (if mounted) stays live even when `open` is false. */
export function casinoChatIsLive(open: boolean, docked: boolean): boolean {
  return open || docked;
}

function formatTime(iso: string): string {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return "";
  return new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" }).format(at);
}

function Avatar({ actor, size = 28 }: { actor: CasinoChatActor; size?: number }) {
  return <CasinoPlayerAvatar actor={actor} size={size} className="casino-chat-avatar-img" />;
}

export function CasinoChatPanel({
  open,
  onClose,
  docked,
}: {
  open: boolean;
  onClose: () => void;
  docked: boolean;
}) {
  const { isAuthed, user } = useSession();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("lobby");
  const [messages, setMessages] = useState<CasinoChatMessage[]>([]);
  const [online, setOnline] = useState<CasinoChatActor[]>([]);
  const [dms, setDms] = useState<CasinoChatThread[]>([]);
  const [peer, setPeer] = useState<CasinoChatActor | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [challenge, setChallenge] = useState<CasinoChatActor | null>(null);
  const [challengeGame, setChallengeGame] = useState("pvp_dice");
  const [challengeStake, setChallengeStake] = useState("50");
  const listRef = useRef<HTMLDivElement>(null);
  const live = casinoChatIsLive(open, docked);
  const myId = Number(user?.telegram_user_id || user?.telegram_id || user?.client_user_id || 0);

  async function loadLobby() {
    const data = await getCasinoChatLobby();
    setMessages(data.messages);
    setOnline(data.online);
  }

  async function loadDms() {
    const data = await getCasinoChatDms();
    setDms(data.dms);
  }

  async function loadPeer(actor: CasinoChatActor) {
    const data = await getCasinoChatDm(actor.user_id);
    setPeer(actor);
    setMessages(data.messages);
    setTab("dms");
  }

  useEffect(() => {
    if (!live || !isAuthed) return;
    void (tab === "lobby" && !peer ? loadLobby() : peer ? loadPeer(peer) : loadDms()).catch((err) => {
      setError(err instanceof Error ? err.message : "Чат недоступен");
    });
  }, [live, isAuthed, tab, peer?.user_id]);

  useEffect(() => {
    if (!live || !isAuthed) return;
    const token = getToken("user");
    const qs = token ? `?access_token=${encodeURIComponent(token)}` : "";
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/user/casino/chat/events${qs}`, { withCredentials: true });
      es.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as {
            type?: string;
            lobby?: boolean;
            message?: CasinoChatMessage;
            user?: CasinoChatActor;
            online?: boolean;
          };
          if (payload.type === "message" && payload.message) {
            const incoming = payload.message;
            const inLobby = Boolean(payload.lobby);
            if (inLobby && tab === "lobby" && !peer) {
              setMessages((current) =>
                current.some((item) => item.id === incoming.id) ? current : [...current, incoming],
              );
            }
            if (!inLobby && peer && incoming.author.user_id === peer.user_id) {
              setMessages((current) =>
                current.some((item) => item.id === incoming.id) ? current : [...current, incoming],
              );
            }
            void loadDms().catch(() => undefined);
          }
          if (payload.type === "presence" && payload.user) {
            const actor = payload.user;
            setOnline((current) => {
              const next = current.filter((item) => item.user_id !== actor.user_id);
              if (payload.online === false) return next;
              return [actor, ...next];
            });
          }
        } catch {
          /* ignore keepalives */
        }
      };
    } catch {
      /* poll only */
    }
    const poll = window.setInterval(() => {
      if (tab === "lobby" && !peer) void loadLobby().catch(() => undefined);
      else if (peer) void loadPeer(peer).catch(() => undefined);
      else void loadDms().catch(() => undefined);
    }, 8000);
    return () => {
      es?.close();
      window.clearInterval(poll);
    };
  }, [live, isAuthed, tab, peer?.user_id]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages.length]);

  async function send() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino");
      return;
    }
    const text = draft.trim();
    if (!text) return;
    setBusy(true);
    setError("");
    try {
      const result = peer
        ? await postCasinoChatDm(peer.user_id, text)
        : await postCasinoChatLobby(text);
      setMessages((current) =>
        current.some((item) => item.id === result.message.id) ? current : [...current, result.message],
      );
      setDraft("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не отправилось");
    } finally {
      setBusy(false);
    }
  }

  async function sendChallenge() {
    if (!challenge) return;
    const amount = Number(challengeStake.replace(",", "."));
    if (!Number.isFinite(amount) || amount <= 0) {
      setError("Укажи ставку");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await postCasinoChatChallenge({
        peer_id: challenge.user_id,
        game_type: challengeGame,
        stake_rub: amount,
        in_lobby: !peer,
      });
      setChallenge(null);
      if (peer) await loadPeer(peer);
      else await loadLobby();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Вызов не создался");
    } finally {
      setBusy(false);
    }
  }

  async function acceptChallenge(gameId: string) {
    setBusy(true);
    setError("");
    try {
      const result = await joinCasinoDuel(gameId);
      navigate(casinoTo(`/casino/duels/${result.game_id}`));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        navigate(casinoTo(`/casino/tables/${gameId}`));
        return;
      }
      setError(err instanceof Error ? err.message : "Не удалось принять");
    } finally {
      setBusy(false);
    }
  }

  const visibleOnline = useMemo(
    () => online.filter((item) => item.user_id !== myId).slice(0, 24),
    [online, myId],
  );

  if (!docked && !open) return null;

  return (
    <aside className={`casino-chat${docked ? " is-docked" : ""}${open ? " is-open" : ""}`} data-casino-chat="">
      <header className="casino-chat-head">
        <MessageCircle size={16} />
        <span>Чат</span>
        <div className="casino-chat-tabs">
          <button type="button" className={tab === "lobby" && !peer ? "is-on" : ""} onClick={() => { setPeer(null); setTab("lobby"); }}>
            Общий
          </button>
          <button
            type="button"
            className={tab === "dms" || peer ? "is-on" : ""}
            onClick={() => {
              setPeer(null);
              setTab("dms");
              void loadDms().catch(() => undefined);
            }}
          >
            Лички
          </button>
        </div>
        <button type="button" className="casino-icon-btn" aria-label="Закрыть чат" onClick={onClose}>
          <X size={16} />
        </button>
      </header>

      {!isAuthed ? (
        <div className="casino-chat-empty">
          <p>Войди, чтобы писать и видеть, кто онлайн.</p>
          <button type="button" className="casino-btn" onClick={() => goCasinoLogin(navigate, "/casino")}>
            Войти
          </button>
        </div>
      ) : (
        <>
          {peer ? (
            <div className="casino-chat-peer">
              <button type="button" className="casino-chat-back" onClick={() => setPeer(null)}>
                ←
              </button>
              <Avatar actor={peer} />
              <span>{peer.display_name}</span>
              <button type="button" className="casino-chat-challenge-btn" onClick={() => setChallenge(peer)}>
                <Swords size={14} /> Вызвать
              </button>
            </div>
          ) : tab === "lobby" ? (
            <div className="casino-chat-online">
              <Users size={12} />
              <span>{online.length} онлайн</span>
              <div className="casino-chat-online-row">
                {visibleOnline.map((actor) => (
                  <button key={actor.user_id} type="button" title={actor.display_name} onClick={() => void loadPeer(actor)}>
                    <Avatar actor={actor} size={24} />
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="casino-chat-list" ref={listRef}>
            {tab === "dms" && !peer
              ? dms.map((thread) => (
                  <button
                    key={thread.room_id}
                    type="button"
                    className="casino-chat-thread"
                    onClick={() => void loadPeer(thread.peer)}
                  >
                    <Avatar actor={thread.peer} />
                    <span>
                      <strong>{thread.peer.display_name}</strong>
                      <em>{thread.last_body || "Нет сообщений"}</em>
                    </span>
                  </button>
                ))
              : messages.map((item) => {
                  const mine = item.author.user_id === myId;
                  const gameId = String(item.payload.game_id || "");
                  const peerId = Number(item.payload.peer_id || 0);
                  return (
                    <div key={item.id} className={`casino-chat-msg${mine ? " is-mine" : ""}`}>
                      {!mine ? (
                        <button type="button" className="casino-chat-msg-avatar" onClick={() => void loadPeer(item.author)}>
                          <Avatar actor={item.author} size={22} />
                        </button>
                      ) : null}
                      <div>
                        <div className="casino-chat-msg-meta">
                          <button type="button" onClick={() => void loadPeer(item.author)}>
                            {item.author.display_name}
                          </button>
                          <time>{formatTime(item.created_at)}</time>
                        </div>
                        <p>{item.body}</p>
                        {item.kind === "challenge" && gameId && peerId === myId && !mine ? (
                          <button type="button" className="casino-btn casino-chat-accept" disabled={busy} onClick={() => void acceptChallenge(gameId)}>
                            Принять
                          </button>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
          </div>

          {error ? <p className="casino-chat-error">{error}</p> : null}

          {challenge ? (
            <div className="casino-chat-challenge">
              <p>Вызов {challenge.display_name}</p>
              <select value={challengeGame} onChange={(event) => setChallengeGame(event.target.value)}>
                {DUEL_GAMES.map((game) => (
                  <option key={game.id} value={game.id}>
                    {game.name}
                  </option>
                ))}
              </select>
              <input value={challengeStake} onChange={(event) => setChallengeStake(event.target.value)} inputMode="decimal" />
              <div>
                <button type="button" className="casino-btn" disabled={busy} onClick={() => void sendChallenge()}>
                  Отправить
                </button>
                <button type="button" className="casino-btn casino-btn-ghost" onClick={() => setChallenge(null)}>
                  Отмена
                </button>
              </div>
            </div>
          ) : (
            <form
              className="casino-chat-compose"
              onSubmit={(event) => {
                event.preventDefault();
                void send();
              }}
            >
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                maxLength={280}
                placeholder={peer ? "Сообщение…" : "В общий чат…"}
              />
              <button type="submit" className="casino-icon-btn" disabled={busy || !draft.trim()} aria-label="Отправить">
                <Send size={16} />
              </button>
            </form>
          )}
        </>
      )}
    </aside>
  );
}
