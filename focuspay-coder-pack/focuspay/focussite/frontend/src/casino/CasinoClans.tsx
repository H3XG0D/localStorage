import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "@/lib/api";
import {
  getCasinoClan,
  getCasinoClanTop,
  getMyCasinoClan,
  postCasinoClanCreate,
  postCasinoClanDisband,
  postCasinoClanInvite,
  postCasinoClanJoin,
  postCasinoClanKick,
  postCasinoClanLeave,
  postCasinoClanTransfer,
  type CasinoClan,
  type CasinoClanTop,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value)} ₽`;
}

function errMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Не удалось выполнить запрос";
}

const TAG_RE = /^[A-Z0-9]{3,8}$/;

function validateCreate(tag: string, name: string): string | null {
  if (!TAG_RE.test(tag.trim().toUpperCase())) return "Тег: 3–8 символов A–Z и 0–9";
  const cleaned = name.trim().replace(/\s+/g, " ");
  if (cleaned.length < 3 || cleaned.length > 32) return "Имя команды: 3–32 символа";
  return null;
}

function validateJoin(code: string): string | null {
  const cleaned = code.replace(/[^A-Z0-9]/gi, "");
  if (cleaned.length < 6 || cleaned.length > 16) return "Неверный код приглашения";
  return null;
}

export function CasinoClans() {
  const { tag } = useParams();
  if (tag) return <CasinoClanPage tag={tag} />;
  return <CasinoClanLobby />;
}

function CasinoClanLobby() {
  const { isAuthed } = useSession();
  const navigate = useNavigate();
  const [top, setTop] = useState<CasinoClanTop | null>(null);
  const [mine, setMine] = useState<CasinoClan | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState("");
  const [tag, setTag] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const ranking = await getCasinoClanTop();
      setTop(ranking);
      if (isAuthed) {
        const row = await getMyCasinoClan();
        setMine(row.clan);
        setEnabled(row.enabled);
      }
      setError("");
    } catch (error) {
      setError(errMessage(error));
    }
  }

  useEffect(() => {
    void load();
  }, [isAuthed]);

  async function onCreate() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/clans");
      return;
    }
    const invalid = validateCreate(tag, name);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    try {
      const result = await postCasinoClanCreate(tag, name);
      navigate(casinoTo(`/casino/clans/${result.clan.tag}`));
    } catch (error) {
      setError(errMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function onJoin() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/clans");
      return;
    }
    const invalid = validateJoin(code);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    try {
      const result = await postCasinoClanJoin(code);
      navigate(casinoTo(`/casino/clans/${result.clan.tag}`));
    } catch (error) {
      setError(errMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="casino-clans" data-casino-clans="1">
      <header className="casino-duels-head">
        <div>
          <h1>Команды</h1>
          <p className="casino-muted">Топ по обороту за московскую неделю. Тег 3–8 символов (A–Z, 0–9). Вступление только по коду. Война кланов — ставки с кошельков игроков, банка у команды нет.</p>
        </div>
        <Link to={casinoTo("/casino/play/clan_war?mode=players")} className="casino-btn casino-btn-ghost">
          Война кланов
        </Link>
      </header>

      {error ? <p className="casino-duel-error">{error}</p> : null}

      {mine ? (
        <section className="casino-section">
          <h2 className="casino-section-title">Моя команда</h2>
          <Link to={casinoTo(`/casino/clans/${mine.tag}`)} className="casino-clan-row" data-casino-my-clan="">
            <strong>[{mine.tag}]</strong>
            <span>{mine.name}</span>
            <span className="casino-muted">{formatRub(mine.wager_rub)}</span>
          </Link>
        </section>
      ) : (
        <section className="casino-section">
          <h2 className="casino-section-title">Создать или вступить</h2>
          {!enabled ? <p className="casino-muted">Кланы сейчас выключены.</p> : null}
          <div className="casino-create-section-grid">
          <form
            className="casino-create-card casino-clan-form"
            data-casino-clan-create=""
            onSubmit={(event) => {
              event.preventDefault();
              void onCreate();
            }}
          >
            <label>
              Тег (3–8)
              <input value={tag} onChange={(event) => setTag(event.target.value.toUpperCase())} maxLength={8} placeholder="ACE" autoComplete="off" />
            </label>
            <label>
              Имя
              <input value={name} onChange={(event) => setName(event.target.value)} maxLength={32} placeholder="Aces" />
            </label>
            <button type="submit" className="casino-btn" disabled={busy || !enabled}>
              Создать
            </button>
          </form>
          <form
            className="casino-duel-create"
            data-casino-clan-join=""
            onSubmit={(event) => {
              event.preventDefault();
              void onJoin();
            }}
          >
            <label>
              Код приглашения
              <input value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} placeholder="ABCD1234" />
            </label>
            <button type="submit" className="casino-btn casino-btn-ghost" disabled={busy || !enabled}>
              Вступить
            </button>
          </form>
          </div>
        </section>
      )}

      <section className="casino-section">
        <h2 className="casino-section-title">Топ недели</h2>
        {(top?.clans.length ?? 0) === 0 ? (
          <p className="casino-muted">Пока пусто. Создайте команду и сыграйте раунд.</p>
        ) : (
          <ol className="casino-clan-list">
            {top?.clans.map((clan, index) => (
              <li key={clan.tag}>
                <Link to={casinoTo(`/casino/clans/${clan.tag}`)} className="casino-clan-row">
                  <span className="casino-muted">{index + 1}</span>
                  <strong>[{clan.tag}]</strong>
                  <span>{clan.name}</span>
                  <span className="casino-muted">{clan.member_count} чел.</span>
                  <span>{formatRub(clan.wager_rub)}</span>
                </Link>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

function CasinoClanPage({ tag }: { tag: string }) {
  const { isAuthed } = useSession();
  const navigate = useNavigate();
  const [clan, setClan] = useState<CasinoClan | null>(null);
  const [mine, setMine] = useState<CasinoClan | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const row = await getCasinoClan(tag);
      setClan(row);
      if (isAuthed) {
        const me = await getMyCasinoClan();
        setMine(me.clan);
      }
      setError("");
    } catch (error) {
      setError(errMessage(error));
      setClan(null);
    }
  }

  useEffect(() => {
    void load();
  }, [tag, isAuthed]);

  const isOwner = Boolean(mine && clan && mine.id === clan.id && mine.is_owner);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await load();
    } catch (error) {
      setError(errMessage(error));
    } finally {
      setBusy(false);
    }
  }

  if (!clan && !error) return <p className="casino-muted">Загрузка…</p>;
  if (!clan) {
    return (
      <div className="casino-clans">
        <p className="casino-duel-error">{error}</p>
        <Link to={casinoTo("/casino/clans")}>К списку</Link>
      </div>
    );
  }

  return (
    <div className="casino-clans" data-casino-clan={clan.tag}>
      <header className="casino-duels-head">
        <div>
          <p className="casino-muted">
            <Link to={casinoTo("/casino/clans")}>Команды</Link>
          </p>
          <h1>
            [{clan.tag}] {clan.name}
          </h1>
          <p className="casino-muted">
            Оборот недели {formatRub(clan.wager_rub)} · {clan.member_count}/{clan.max_members}
          </p>
        </div>
      </header>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {isOwner && mine?.invite_code ? (
        <p className="casino-clan-code" data-casino-invite="">
          Код: <code>{mine.invite_code}</code>
          <button type="button" className="casino-btn casino-btn-ghost" disabled={busy} onClick={() => void run(() => postCasinoClanInvite())}>
            Новый код
          </button>
        </p>
      ) : null}
      <section className="casino-section">
        <h2 className="casino-section-title">Состав</h2>
        <ul className="casino-clan-list">
          {(clan.members ?? []).map((member) => (
            <li key={member.user_id} className="casino-clan-row">
              <span>
                {member.display_name}
                {member.role === "owner" ? " · владелец" : ""}
              </span>
              <span>{formatRub(member.wager_rub)}</span>
              {isOwner && member.role !== "owner" ? (
                <span className="casino-clan-actions">
                  <button type="button" className="casino-btn casino-btn-ghost" disabled={busy} onClick={() => void run(() => postCasinoClanKick(member.user_id))}>
                    Кик
                  </button>
                  <button type="button" className="casino-btn casino-btn-ghost" disabled={busy} onClick={() => void run(() => postCasinoClanTransfer(member.user_id))}>
                    Владелец
                  </button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
      {mine && mine.id === clan.id ? (
        <p className="casino-clan-actions">
          {isOwner ? (
            <button
              type="button"
              className="casino-btn casino-btn-lose"
              disabled={busy}
              onClick={() => {
                if (window.confirm("Распустить команду?")) void run(() => postCasinoClanDisband().then(() => navigate(casinoTo("/casino/clans"))));
              }}
            >
              Распустить
            </button>
          ) : (
            <button type="button" className="casino-btn casino-btn-ghost" disabled={busy} onClick={() => void run(() => postCasinoClanLeave().then(() => navigate(casinoTo("/casino/clans"))))}>
              Выйти
            </button>
          )}
        </p>
      ) : null}
    </div>
  );
}
