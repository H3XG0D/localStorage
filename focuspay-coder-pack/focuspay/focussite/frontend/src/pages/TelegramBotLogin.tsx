import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Send } from "lucide-react";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  telegramBotComplete,
  telegramBotStart,
  telegramBotWait,
  type LoginSuccess,
} from "@/lib/auth";
import { authPathWithNext, resolvePostLoginPath } from "@/lib/postLoginPath";
import { useSession } from "@/lib/session";

const POLL_MS = 1500;

function isLoginSuccess(value: unknown): value is LoginSuccess {
  if (!value || typeof value !== "object") return false;
  const row = value as { access_token?: unknown; user?: unknown };
  return typeof row.access_token === "string" && row.user != null;
}

export function TelegramBotLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  const { adopt, isAuthed, loading } = useSession();

  const locState = location.state as { from?: string; casinoBackground?: unknown } | null;
  const params = new URLSearchParams(location.search);
  const ticket = (params.get("ticket") || "").trim().toLowerCase();
  const from = resolvePostLoginPath(locState?.from || params.get("next"), "/casino");
  const nextPath = from.startsWith("/casino") ? from : "/casino";
  const passwordHref = authPathWithNext("/login", nextPath);

  const [deepLink, setDeepLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const ticketDone = useRef(false);

  function goAfterLogin(path = nextPath) {
    const dest = path.startsWith("/casino") ? path : nextPath;
    if (locState?.casinoBackground && dest.startsWith("/casino")) {
      navigate(dest, { replace: true, state: { casinoBackground: locState.casinoBackground } });
      return;
    }
    navigate(dest, { replace: true });
  }

  function adoptLogin(result: LoginSuccess) {
    adopt(result);
    toast.success("Вход через Telegram");
    const returned = "return_path" in result ? String((result as { return_path?: string }).return_path || "") : "";
    goAfterLogin(returned.startsWith("/casino") ? returned : nextPath);
  }

  useEffect(() => {
    if (loading || !isAuthed) return;
    goAfterLogin();
    // Bounce after session boot or a completed login.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, loading]);

  useEffect(() => {
    if (!ticket || ticketDone.current) return;
    ticketDone.current = true;
    void (async () => {
      try {
        const result = await telegramBotComplete(ticket);
        if (isLoginSuccess(result)) adoptLogin(result);
        else setError("Не удалось войти. Откройте бота ещё раз.");
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Ссылка входа истекла. Нажмите Start в боте ещё раз.");
        ticketDone.current = false;
      }
    })();
    // Ticket is consumed once per landing URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticket]);

  useEffect(() => {
    if (ticket) return;
    let cancelled = false;
    let timer: number | undefined;
    let waitToken = "";

    void (async () => {
      try {
        const startedLogin = await telegramBotStart(nextPath);
        if (cancelled) return;
        setDeepLink(startedLogin.deep_link);
        waitToken = startedLogin.wait_token;
        window.open(startedLogin.deep_link, "_blank", "noopener,noreferrer");
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : "Не удалось начать вход через бота");
        }
        return;
      }

      const poll = async () => {
        if (cancelled || !waitToken) return;
        try {
          const result = await telegramBotWait(waitToken);
          if (cancelled) return;
          if (isLoginSuccess(result) && result.status === "ready") {
            adoptLogin(result);
            return;
          }
          if (result.status === "expired") {
            setError("Время на вход вышло. Нажмите «Открыть бота» ещё раз.");
            return;
          }
          if (result.status === "consumed") return;
        } catch (e) {
          if (!cancelled) {
            setError(e instanceof ApiError ? e.message : "Не удалось проверить вход");
          }
        }
        timer = window.setTimeout(() => void poll(), POLL_MS);
      };
      timer = window.setTimeout(() => void poll(), POLL_MS);
    })();

    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
    // Start/poll once per next path or manual retry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticket, nextPath, round]);

  function restart() {
    setError(null);
    setDeepLink(null);
    setRound((n) => n + 1);
  }

  return (
    <AuthShell
      title="Вход в FocusBet"
      subtitle="Откроется игровой бот FocusBet. Нажмите Start — номер телефона не нужен."
    >
      <div className="flex flex-col gap-5" data-casino-tg-bot-login="">
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        {deepLink ? (
          <Button size="lg" className="w-full" asChild>
            <a href={deepLink} target="_blank" rel="noopener noreferrer">
              <Send data-icon="inline-start" />
              Открыть бота и нажать Start
            </a>
          </Button>
        ) : (
          <Button size="lg" className="w-full" disabled={!error} onClick={restart}>
            {error ? "Попробовать снова" : "Открываем бота…"}
          </Button>
        )}
        {error && deepLink ? (
          <Button variant="outline" className="w-full" onClick={restart}>
            Новая ссылка
          </Button>
        ) : null}
        <p className="text-center text-sm text-muted-foreground">
          После Start вернитесь сюда — вход подхватится сам. Или нажмите «Открыть казино» в боте.
        </p>
        <p className="text-center text-sm text-muted-foreground">
          Есть логин и пароль?{" "}
          <Link to={passwordHref} state={locState} className="font-medium text-foreground underline-offset-4 hover:underline">
            Войти так
          </Link>
        </p>
      </div>
    </AuthShell>
  );
}
