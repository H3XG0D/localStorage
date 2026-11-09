import { useState } from "react";
import { KeyRound, Loader2, Send, ShieldCheck, ShieldX } from "lucide-react";
import { toast } from "sonner";
import { CabinetLayout } from "@/components/CabinetLayout";
import { TelegramLoginButton } from "@/components/TelegramLoginButton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { changePassword, telegramLink, totpConfirm, totpDisable, totpSetup } from "@/lib/auth";
import { useSession } from "@/lib/session";

export function CabinetSettings() {
  const { user, refresh } = useSession();

  // password
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwBusy, setPwBusy] = useState(false);

  // totp
  const [totpUri, setTotpUri] = useState<string | null>(null);
  const [totpSecret, setTotpSecret] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [totpBusy, setTotpBusy] = useState(false);
  const [disablePw, setDisablePw] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const enabled = !!user?.totp_enabled;

  async function onChangePassword() {
    if (newPw.length < 6) return toast.error("Пароль — минимум 6 символов");
    setPwBusy(true);
    try {
      await changePassword(curPw, newPw);
      toast.success("Пароль изменён");
      setCurPw("");
      setNewPw("");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось изменить пароль");
    } finally {
      setPwBusy(false);
    }
  }

  async function onTotpSetup() {
    setTotpBusy(true);
    try {
      const r = await totpSetup();
      setTotpUri(r.uri);
      setTotpSecret(r.secret);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось начать настройку");
    } finally {
      setTotpBusy(false);
    }
  }

  async function onTotpConfirm() {
    setTotpBusy(true);
    try {
      await totpConfirm(totpCode.trim());
      toast.success("2FA включена");
      setTotpUri(null);
      setTotpSecret(null);
      setTotpCode("");
      await refresh();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Неверный код");
    } finally {
      setTotpBusy(false);
    }
  }

  async function onTotpDisable() {
    setTotpBusy(true);
    try {
      await totpDisable(disablePw, disableCode.trim());
      toast.success("2FA отключена");
      setDisablePw("");
      setDisableCode("");
      await refresh();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось отключить 2FA");
    } finally {
      setTotpBusy(false);
    }
  }

  async function onTelegramLink(payload: Record<string, unknown>) {
    try {
      await telegramLink(payload);
      toast.success("Telegram привязан");
      await refresh();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось привязать Telegram");
    }
  }

  return (
    <CabinetLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Настройки</h1>
          <p className="mt-1 text-sm text-muted-foreground">Безопасность аккаунта и вход.</p>
        </div>

        {/* password */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <KeyRound className="size-5" />
              <CardTitle>Смена пароля</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-col gap-2">
              <Label htmlFor="curpw">Текущий пароль</Label>
              <Input id="curpw" type="password" value={curPw} onChange={(e) => setCurPw(e.target.value)} autoComplete="current-password" />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="newpw">Новый пароль</Label>
              <Input id="newpw" type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} autoComplete="new-password" placeholder="Минимум 6 символов" />
            </div>
            <Button onClick={onChangePassword} disabled={pwBusy || !curPw || !newPw}>
              {pwBusy ? <Loader2 className="size-4 animate-spin" data-icon="inline-start" /> : null}
              Сохранить пароль
            </Button>
          </CardContent>
        </Card>

        {/* 2FA */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              {enabled ? <ShieldCheck className="size-5" /> : <ShieldX className="size-5 text-muted-foreground" />}
              <CardTitle>Двухфакторная аутентификация</CardTitle>
            </div>
            <CardDescription>{enabled ? "2FA включена." : "Защитите вход кодом из приложения-аутентификатора."}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {!enabled && !totpUri && (
              <Button variant="outline" onClick={onTotpSetup} disabled={totpBusy}>
                {totpBusy ? <Loader2 className="size-4 animate-spin" data-icon="inline-start" /> : <ShieldCheck data-icon="inline-start" />}
                Настроить 2FA
              </Button>
            )}
            {!enabled && totpUri && (
              <div className="space-y-3">
                <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm">
                  <p className="text-muted-foreground">Добавьте секрет в приложение (Google Authenticator и т.п.):</p>
                  <p className="mt-2 select-all break-all font-mono text-xs">{totpSecret}</p>
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="totpcode">Код из приложения</Label>
                  <Input id="totpcode" inputMode="numeric" value={totpCode} onChange={(e) => setTotpCode(e.target.value)} placeholder="000000" className="font-mono tracking-[0.3em]" maxLength={8} />
                </div>
                <Button onClick={onTotpConfirm} disabled={totpBusy || totpCode.length < 6}>
                  {totpBusy ? <Loader2 className="size-4 animate-spin" data-icon="inline-start" /> : null}
                  Подтвердить и включить
                </Button>
              </div>
            )}
            {enabled && (
              <div className="space-y-3">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="dispw">Текущий пароль</Label>
                  <Input id="dispw" type="password" value={disablePw} onChange={(e) => setDisablePw(e.target.value)} />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="discode">Код 2FA</Label>
                  <Input id="discode" inputMode="numeric" value={disableCode} onChange={(e) => setDisableCode(e.target.value)} placeholder="000000" className="font-mono tracking-[0.3em]" maxLength={8} />
                </div>
                <Button variant="outline" onClick={onTotpDisable} disabled={totpBusy || !disablePw || !disableCode} className="text-destructive hover:text-destructive">
                  {totpBusy ? <Loader2 className="size-4 animate-spin" data-icon="inline-start" /> : <ShieldX data-icon="inline-start" />}
                  Отключить 2FA
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* telegram link */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Send className="size-5" />
              <CardTitle>Telegram</CardTitle>
            </div>
            <CardDescription>
              {user?.telegram_id ? "Telegram привязан к аккаунту." : "Привяжите Telegram для входа в один клик."}
            </CardDescription>
          </CardHeader>
          {!user?.telegram_id && (
            <CardContent>
              <TelegramLoginButton onAuth={onTelegramLink} returnPath="/cabinet/settings" />
            </CardContent>
          )}
        </Card>
      </div>
    </CabinetLayout>
  );
}
