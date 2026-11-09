import { useEffect, useState } from "react";
import { BellRing, Camera, ChevronRight, UserRound } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import {
  getCasinoPlayer,
  patchCasinoPlayerLook,
  uploadCasinoPlayerAvatar,
  type CasinoPlayerProfile,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CasinoPlayerChip } from "./CasinoPlayerChip";
import { CASINO_LOOK_EVENT } from "./gameCatalog";

export function CasinoPlayerSettings() {
  const { isAuthed, loading } = useSession();
  const navigate = useNavigate();
  const [data, setData] = useState<CasinoPlayerProfile | null>(null);
  const [nickname, setNickname] = useState("");
  const [notifyOpen, setNotifyOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const savedName = data?.player.display_name ?? "";
  const savedNotify = Boolean(data?.own?.notify_open_tables);
  const dirty = Boolean(data) && (nickname !== savedName || notifyOpen !== savedNotify);

  useEffect(() => {
    if (!dirty) return;
    const message = "Изменения не сохранены. Уйти без сохранения?";
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) return;
      if (anchor.target && anchor.target !== "_self") return;
      if (anchor.hasAttribute("download")) return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("mailto:") || href.startsWith("tel:") || href.startsWith("#")) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      if (window.confirm(message)) return;
      event.preventDefault();
      event.stopPropagation();
    };
    const onPopState = () => {
      if (!window.confirm(message)) window.history.go(1);
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("popstate", onPopState);
    };
  }, [dirty]);

  useEffect(() => {
    if (loading) return;
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/settings");
      return;
    }
    getCasinoPlayer("me")
      .then((payload) => {
        setData(payload);
        setNickname(payload.player.display_name);
        setNotifyOpen(Boolean(payload.own?.notify_open_tables));
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось открыть настройки"));
  }, [isAuthed, loading, navigate]);

  async function onSaveNick() {
    setBusy(true);
    try {
      const next = await patchCasinoPlayerLook(nickname.trim(), { notify_open_tables: notifyOpen });
      setData(next);
      setNickname(next.player.display_name);
      setNotifyOpen(Boolean(next.own?.notify_open_tables));
      window.dispatchEvent(new Event(CASINO_LOOK_EVENT));
      toast.success("Сохранено");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не сохранилось");
    } finally {
      setBusy(false);
    }
  }

  async function onAvatar(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      const next = await uploadCasinoPlayerAvatar(file);
      setData(next);
      window.dispatchEvent(new Event(CASINO_LOOK_EVENT));
      toast.success("Аватар обновлён");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не загрузился");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="casino-profile casino-player-settings" data-casino-player-settings="">
      <nav className="casino-crumb" aria-label="Навигация">
        <Link to={casinoTo("/casino")}>Лобби</Link>
        <span className="casino-crumb-sep" aria-hidden>
          /
        </span>
        <Link to={casinoTo("/casino/me")}>Профиль</Link>
        <span className="casino-crumb-sep" aria-hidden>
          /
        </span>
        <span>Настройки</span>
      </nav>
      <div className="casino-settings-titlebar">
        <div>
          <p className="casino-settings-eyebrow">Профиль</p>
          <h1>Настройки</h1>
          <p className="casino-muted">Управляйте тем, как вас видят за столом.</p>
        </div>
        <Link to={casinoTo("/casino/me")} className="casino-settings-view-link">
          Профиль <ChevronRight size={16} />
        </Link>
      </div>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {data ? (
        <>
          <header className="casino-settings-profile-card">
            <div className="casino-settings-avatar-wrap">
              <CasinoPlayerChip actor={data.player} linked={false} size={64} />
              <label className="casino-settings-avatar-action" title="Изменить аватар">
                <Camera size={15} />
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={(event) => void onAvatar(event.target.files?.[0])}
                />
              </label>
            </div>
            <div className="casino-settings-profile-copy">
              <h2>{data.player.display_name}</h2>
              <p className="casino-muted">Уровень {data.level.index} · Имя и аватар профиля</p>
            </div>
          </header>
          <section className="casino-settings-card" aria-label="Публичное имя">
            <div className="casino-settings-card-heading">
              <span className="casino-settings-icon"><UserRound size={18} /></span>
              <div><h2>Имя за столом</h2><p>Так вас видят соперники и собеседники</p></div>
            </div>
            <label className="casino-field">
              Отображаемое имя
              <input value={nickname} onChange={(event) => setNickname(event.target.value)} maxLength={32} placeholder="Например, Focus Hero" autoComplete="nickname" />
            </label>
            <p className="casino-settings-meta"><span>Отображаемое имя</span><strong>{nickname.length}/32</strong></p>
            <p className="casino-settings-help">До 32 символов. Изменение применится после сохранения.</p>
          </section>
          <section className="casino-settings-card" aria-label="Уведомления">
            <div className="casino-settings-card-heading">
              <span className="casino-settings-icon"><BellRing size={18} /></span>
              <div><h2>Уведомления</h2><p>Только личные сообщения от FocusBet</p></div>
            </div>
            <label className="casino-settings-switch">
              <span><strong>Новые столы блэкджека</strong><small>Получать уведомление в Telegram, когда открывается стол</small></span>
              <input type="checkbox" checked={notifyOpen} onChange={(event) => setNotifyOpen(event.target.checked)} data-casino-notify-tables="" />
            </label>
          </section>
          <div className="casino-duels-actions casino-settings-actions">
            <button type="button" className="casino-btn casino-settings-save" disabled={busy || !dirty} onClick={() => void onSaveNick()}>
              {busy ? "Сохранение…" : "Сохранить изменения"}
            </button>
          </div>
        </>
      ) : !error ? (
        <p className="casino-muted">Загрузка…</p>
      ) : null}
    </div>
  );
}
