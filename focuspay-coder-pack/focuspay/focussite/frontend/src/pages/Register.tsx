import { useRef, useState, type FormEvent } from "react";
import { ArrowRight, Copy, Eye, EyeOff, LockKeyhole, ShieldCheck, UserRound } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { AuthShell } from "@/components/AuthShell";
import { CaptchaField, type CaptchaHandle } from "@/components/CaptchaField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { register } from "@/lib/auth";
import { authPathWithNext, resolvePostLoginPath } from "@/lib/postLoginPath";
import { useSession } from "@/lib/session";

export function Register() {
  const navigate = useNavigate();
  const location = useLocation();
  const { adopt } = useSession();
  const captchaRef = useRef<CaptchaHandle>(null);

  const locState = location.state as { from?: string; casinoBackground?: unknown } | null;
  const nextQuery = new URLSearchParams(location.search).get("next");
  const from = resolvePostLoginPath(locState?.from || nextQuery);
  const loginHref = authPathWithNext("/login", from);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [captchaAnswer, setCaptchaAnswer] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null);

  function goAfterRegister() {
    if (locState?.casinoBackground && from.startsWith("/casino")) {
      navigate(from, { replace: true, state: { casinoBackground: locState.casinoBackground } });
      return;
    }
    navigate(from, { replace: true });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password.length < 6) {
      toast.error("Пароль — минимум 6 символов");
      return;
    }
    setPending(true);
    try {
      const result = await register(username, password, displayName || undefined, captchaToken, captchaAnswer);
      adopt(result);
      if (result.recovery_code) {
        setRecoveryCode(result.recovery_code);
      } else {
        toast.success("Аккаунт создан");
        goAfterRegister();
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось зарегистрироваться");
      captchaRef.current?.refresh();
    } finally {
      setPending(false);
    }
  }

  if (recoveryCode) {
    return (
      <AuthShell title="Сохраните код восстановления" subtitle="Это единственный способ восстановить доступ, если вы забудете пароль.">
        <div className="flex flex-col gap-5">
          <div className="rounded-xl border border-border bg-muted/40 p-5 text-center">
            <p className="text-xs uppercase tracking-[.16em] text-muted-foreground">Код восстановления</p>
            <p className="mt-3 select-all break-all font-mono text-2xl font-semibold tracking-wider">{recoveryCode}</p>
          </div>
          <Button
            variant="outline"
            onClick={() => {
              navigator.clipboard?.writeText(recoveryCode).then(
                () => toast.success("Код скопирован"),
                () => toast.error("Не удалось скопировать"),
              );
            }}
          >
            <Copy data-icon="inline-start" />
            Скопировать код
          </Button>
          <div className="flex items-start gap-2 rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-foreground" />
            <span>Запишите код и храните в надёжном месте. Мы не сможем показать его повторно.</span>
          </div>
          <Button size="lg" className="w-full" onClick={() => goAfterRegister()}>
            Я сохранил код — продолжить
            <ArrowRight data-icon="inline-end" />
          </Button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Создать аккаунт" subtitle="Регистрация занимает меньше минуты. Гостевые заявки отключены.">
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
              placeholder="Придумайте логин"
              className="pl-10"
              required
            />
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="displayName">Имя (необязательно)</Label>
          <Input
            id="displayName"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Как к вам обращаться"
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="password">Пароль</Label>
          <div className="relative">
            <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Минимум 6 символов"
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
          {pending ? "Создаём…" : "Зарегистрироваться"}
          {!pending && <ArrowRight data-icon="inline-end" />}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-muted-foreground">
        Уже есть аккаунт?{" "}
        <Link to={loginHref} state={locState} className="font-medium text-foreground underline-offset-4 hover:underline">
          Войти
        </Link>
      </p>
    </AuthShell>
  );
}
