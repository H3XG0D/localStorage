import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff, LockKeyhole, ShieldCheck, UserRound } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { AuthShell } from "@/components/AuthShell";
import { CaptchaField, type CaptchaHandle } from "@/components/CaptchaField";
import { TelegramLoginButton } from "@/components/TelegramLoginButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { ApiError } from "@/lib/api";
import { is2FA, isPartner, login, login2FA, persistToken, telegramAuth } from "@/lib/auth";
import { isOnionHost } from "@/lib/onion";
import { authPathWithNext, resolvePostLoginPath } from "@/lib/postLoginPath";
import { useSession } from "@/lib/session";
import { consumeTelegramOauthResult, stripTelegramOauthParams } from "@/lib/telegramOauth";

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { adopt, refresh, isAuthed, loading } = useSession();
  const captchaRef = useRef<CaptchaHandle>(null);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [captchaAnswer, setCaptchaAnswer] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);

  // 2FA step
  const [preAuthToken, setPreAuthToken] = useState<string | null>(null);
  const [code, setCode] = useState("");

  const locState = location.state as { from?: string; casinoBackground?: unknown } | null;
  const nextQuery = new URLSearchParams(location.search).get("next");
  const from = resolvePostLoginPath(locState?.from || nextQuery);
  const registerHref = authPathWithNext("/register", from);
  const telegramReturnPath = authPathWithNext("/login", from);

  function goAfterLogin() {
    if (locState?.casinoBackground && from.startsWith("/casino")) {
      navigate(from, { replace: true, state: { casinoBackground: locState.casinoBackground } });
      return;
    }
    navigate(from, { replace: true });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    try {
      const result = await login(username, password, captchaToken, captchaAnswer);
      if (isPartner(result)) {
        // Partner account matched buyer login — route to the partner portal.
        if (result.access_token) persistToken("partner", result.access_token);
        toast.success("Вход партнёра");
        navigate("/partner", { replace: true });
        return;
      }
      if (is2FA(result)) {
        setPreAuthToken(result.pre_auth_token);
        toast.info("Введите код из приложения-аутентификатора");
        return;
      }
      adopt(result);
      toast.success("Добро пожаловать");
      goAfterLogin();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось войти");
      captchaRef.current?.refresh();
    } finally {
      setPending(false);
    }
  }

  async function submit2FA(event: FormEvent) {
    event.preventDefault();
    if (!preAuthToken) return;
    setPending(true);
    try {
      const result = await login2FA(preAuthToken, code.trim());
      adopt(result);
      toast.success("Добро пожаловать");
      goAfterLogin();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Неверный код");
    } finally {
      setPending(false);
    }
  }

  async function onTelegram(payload: Record<string, unknown>) {
    try {
      const result = await telegramAuth(payload);
      adopt(result);
      await refresh();
      toast.success("Вход через Telegram");
      goAfterLogin();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось войти через Telegram");
    }
  }

  useEffect(() => {
    const payload = consumeTelegramOauthResult(location.search, location.hash);
    if (!payload) return;
    const cleanSearch = stripTelegramOauthParams(location.search);
    if (location.hash || cleanSearch !== (location.search || "")) {
      navigate({ pathname: "/login", search: cleanSearch, hash: "" }, { replace: true, state: locState });
    }
    void onTelegram(payload);
    // OAuth return is consumed once per hash; from/locState are from the landing URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (loading || !isAuthed) return;
    goAfterLogin();
    // Bounce after session boot (F5 race from casino) or a completed login.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, loading]);

  if (preAuthToken) {
    return (
      <AuthShell title="Подтверждение входа" subtitle="Введите шестизначный код из приложения-аутентификатора.">
        <form onSubmit={submit2FA} className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label htmlFor="code">Код 2FA</Label>
            <div className="relative">
              <ShieldCheck className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="000000"
                className="pl-10 font-mono tracking-[0.3em]"
                maxLength={8}
                required
                autoFocus
              />
            </div>
          </div>
          <Button type="submit" size="lg" className="w-full" disabled={pending}>
            {pending ? "Проверяем…" : "Подтвердить"}
            {!pending && <ArrowRight data-icon="inline-end" />}
          </Button>
          <button
            type="button"
            className="text-center text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            onClick={() => { setPreAuthToken(null); setCode(""); }}
          >
            Вернуться к вводу пароля
          </button>
        </form>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Вход в аккаунт" subtitle="Войдите, чтобы оформлять обмены и следить за заявками.">
      <form onSubmit={submit} className="flex flex-col gap-5">
        <div className="flex flex-col gap-2">
          <Label htmlFor="username">Логин</Label>
          <div className="relative">
            <UserRound className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Введите логин"
              className="pl-10"
              required
            />
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Пароль</Label>
            <Link to="/forgot" className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
              Забыли пароль?
            </Link>
          </div>
          <div className="relative">
            <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Введите пароль"
              className="pl-10 pr-11"
              required
            />
            <button
              type="button"
              aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
              className="absolute right-2 top-1/2 flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
              onClick={() => setShowPassword((v) => !v)}
            >
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
        </div>

        <CaptchaField ref={captchaRef} token={captchaToken} answer={captchaAnswer} onToken={setCaptchaToken} onAnswer={setCaptchaAnswer} />

        <Button type="submit" size="lg" className="mt-1 w-full" disabled={pending}>
          {pending ? "Проверяем…" : "Войти"}
          {!pending && <ArrowRight data-icon="inline-end" />}
        </Button>
      </form>

      {!isOnionHost() && (
        <>
          <div className="my-6 flex items-center gap-3 text-xs text-muted-foreground">
            <Separator className="flex-1" />
            или
            <Separator className="flex-1" />
          </div>

          {window.location.hostname === "127.0.0.1" ? (
            <p className="text-center text-xs text-muted-foreground">
              Виджет Telegram на 127.0.0.1 не открывается — BotFather принимает только домен. Войдите логином и паролем.
            </p>
          ) : (
            <TelegramLoginButton onAuth={onTelegram} returnPath={telegramReturnPath} />
          )}
        </>
      )}

      <p className="mt-6 text-center text-sm text-muted-foreground">
        Нет аккаунта?{" "}
        <Link to={registerHref} state={locState} className="font-medium text-foreground underline-offset-4 hover:underline">
          Зарегистрироваться
        </Link>
      </p>
    </AuthShell>
  );
}
