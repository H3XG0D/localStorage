import { useState, type FormEvent } from "react";
import { ArrowRight, Copy, KeyRound, LockKeyhole, UserRound } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { forgotRecover } from "@/lib/auth";

export function Forgot() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [newCode, setNewCode] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (newPassword.length < 6) {
      toast.error("Пароль — минимум 6 символов");
      return;
    }
    setPending(true);
    try {
      const res = await forgotRecover(username, recoveryCode.trim(), newPassword);
      setNewCode(res.recovery_code);
      toast.success("Пароль обновлён");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось восстановить доступ");
    } finally {
      setPending(false);
    }
  }

  if (newCode) {
    return (
      <AuthShell title="Пароль обновлён" subtitle="Сохраните новый код восстановления — прежний больше не действует.">
        <div className="flex flex-col gap-5">
          <div className="rounded-xl border border-border bg-muted/40 p-5 text-center">
            <p className="text-xs uppercase tracking-[.16em] text-muted-foreground">Новый код восстановления</p>
            <p className="mt-3 select-all break-all font-mono text-2xl font-semibold tracking-wider">{newCode}</p>
          </div>
          <Button
            variant="outline"
            onClick={() =>
              navigator.clipboard?.writeText(newCode).then(
                () => toast.success("Код скопирован"),
                () => toast.error("Не удалось скопировать"),
              )
            }
          >
            <Copy data-icon="inline-start" />
            Скопировать код
          </Button>
          <Button size="lg" className="w-full" onClick={() => navigate("/login", { replace: true })}>
            Перейти ко входу
            <ArrowRight data-icon="inline-end" />
          </Button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Восстановление доступа" subtitle="Введите логин, код восстановления и новый пароль.">
      <form onSubmit={submit} className="flex flex-col gap-5">
        <div className="flex flex-col gap-2">
          <Label htmlFor="username">Логин</Label>
          <div className="relative">
            <UserRound className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Ваш логин" className="pl-10" required />
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="recovery">Код восстановления</Label>
          <div className="relative">
            <KeyRound className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="recovery"
              value={recoveryCode}
              onChange={(e) => setRecoveryCode(e.target.value)}
              placeholder="Код, выданный при регистрации"
              className="pl-10 font-mono"
              required
            />
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="newPassword">Новый пароль</Label>
          <div className="relative">
            <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="newPassword"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Минимум 6 символов"
              className="pl-10"
              required
            />
          </div>
        </div>
        <Button type="submit" size="lg" className="mt-1 w-full" disabled={pending}>
          {pending ? "Обновляем…" : "Сбросить пароль"}
          {!pending && <ArrowRight data-icon="inline-end" />}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Вспомнили пароль?{" "}
        <Link to="/login" className="font-medium text-foreground underline-offset-4 hover:underline">
          Войти
        </Link>
      </p>
    </AuthShell>
  );
}
