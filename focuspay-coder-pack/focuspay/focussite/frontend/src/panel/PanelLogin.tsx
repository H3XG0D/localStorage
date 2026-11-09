// Panel login (admin or operator). Handles the optional 2FA second step.
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { PanelApiError } from "@/panel/lib/panelApi";
import { adoptPanelToken, needs2FA, panelLogin, panelLogin2FA } from "@/panel/lib/panelAuth";
import { usePanelSession } from "@/panel/lib/panelSession";
import { Button, Field, Input } from "@/panel/ui/primitives";

export function PanelLogin({ redirectTo }: { redirectTo: string }) {
  const { scope, setAccount } = usePanelSession();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preAuth, setPreAuth] = useState<string | null>(null);
  const [code, setCode] = useState("");

  const title = scope === "admin" ? "Центр управления" : "Рабочее место оператора";
  const subtitle = scope === "admin" ? "Панель администратора FocusPay" : "Панель оператора FocusPay";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const r = await panelLogin(scope, username, password);
      if (needs2FA(r)) {
        setPreAuth(r.pre_auth_token);
        return;
      }
      setAccount(adoptPanelToken(scope, r));
      navigate(redirectTo, { replace: true });
    } catch (e) {
      setError(e instanceof PanelApiError ? e.message : "Не удалось войти");
    } finally {
      setPending(false);
    }
  }

  async function submit2FA(e: FormEvent) {
    e.preventDefault();
    if (!preAuth) return;
    setPending(true);
    setError(null);
    try {
      const r = await panelLogin2FA(scope, preAuth, code.trim());
      setAccount(adoptPanelToken(scope, r));
      navigate(redirectTo, { replace: true });
    } catch (e) {
      setError(e instanceof PanelApiError ? e.message : "Неверный код");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-[var(--bg-base)] p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-[var(--radius)] bg-[var(--text-primary)] text-[var(--text-inverse)]">
            <svg width="20" height="20" viewBox="0 0 18 18" fill="none">
              <path d="M4 6h10M4 9h7M4 12h8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <div className="text-[15px] font-bold">{title}</div>
            <div className="text-[12px] text-[var(--text-muted)]">{subtitle}</div>
          </div>
        </div>

        <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-surface)] p-6">
          {!preAuth ? (
            <form onSubmit={submit} className="flex flex-col gap-4">
              <Field label="Логин">
                <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required />
              </Field>
              <Field label="Пароль">
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
              </Field>
              {error && <p className="text-[12px] text-[var(--red)]">{error}</p>}
              <Button type="submit" variant="primary" disabled={pending} className="mt-1 w-full">
                {pending ? "Проверяем…" : "Войти"}
              </Button>
            </form>
          ) : (
            <form onSubmit={submit2FA} className="flex flex-col gap-4">
              <Field label="Код 2FA">
                <Input
                  inputMode="numeric"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="000000"
                  className="font-mono tracking-[0.3em]"
                  maxLength={8}
                  autoFocus
                  required
                />
              </Field>
              {error && <p className="text-[12px] text-[var(--red)]">{error}</p>}
              <Button type="submit" variant="primary" disabled={pending} className="w-full">
                {pending ? "Проверяем…" : "Подтвердить"}
              </Button>
              <button type="button" className="text-[12px] text-[var(--text-muted)] hover:text-[var(--text-primary)]" onClick={() => { setPreAuth(null); setCode(""); }}>
                ← Назад
              </button>
            </form>
          )}
        </div>
        <p className="mt-5 text-center text-[11px] text-[var(--text-muted)]">Доступ только для персонала FocusPay. Действия журналируются.</p>
      </div>
    </div>
  );
}
