import { useState } from "react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { panelChangePassword, panelTotpConfirm, panelTotpDisable, panelTotpSetup } from "@/panel/lib/panelAuth";
import { usePanelSession } from "@/panel/lib/panelSession";
import { Button, Card, Field, Input, PageHeader } from "@/panel/ui/primitives";

export function AdminSettings() {
  const { account, refresh } = usePanelSession();
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [totpUri, setTotpUri] = useState<string | null>(null);
  const [totpSecret, setTotpSecret] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [disPw, setDisPw] = useState("");
  const [disCode, setDisCode] = useState("");
  const enabled = !!account?.totp_enabled;

  async function wrap(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
      throw e;
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Настройки" subtitle="Пароль и двухфакторная защита" />

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">Смена пароля</div>
        <div className="flex max-w-sm flex-col gap-3">
          <Field label="Текущий пароль">
            <Input type="password" value={curPw} onChange={(e) => setCurPw(e.target.value)} />
          </Field>
          <Field label="Новый пароль">
            <Input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="Минимум 6 символов" />
          </Field>
          <Button
            variant="primary"
            disabled={busy || !curPw || newPw.length < 6}
            onClick={() =>
              wrap(() => panelChangePassword("admin", curPw, newPw), "Пароль изменён").then(() => {
                setCurPw("");
                setNewPw("");
              }).catch(() => undefined)
            }
          >
            Сохранить пароль
          </Button>
        </div>
      </Card>

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">Двухфакторная аутентификация · {enabled ? "включена" : "выключена"}</div>
        {!enabled && !totpUri && (
          <Button variant="secondary" disabled={busy} onClick={() => wrap(async () => {
            const r = await panelTotpSetup("admin");
            setTotpUri(r.uri);
            setTotpSecret(r.secret);
          }, "Отсканируйте секрет").catch(() => undefined)}>
            Настроить 2FA
          </Button>
        )}
        {!enabled && totpUri && (
          <div className="flex max-w-sm flex-col gap-3">
            <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 text-[12px]">
              Секрет: <span className="select-all break-all font-mono">{totpSecret}</span>
            </div>
            <Field label="Код из приложения">
              <Input inputMode="numeric" value={totpCode} onChange={(e) => setTotpCode(e.target.value)} className="font-mono tracking-[0.3em]" maxLength={8} />
            </Field>
            <Button variant="primary" disabled={busy || totpCode.length < 6} onClick={() => wrap(() => panelTotpConfirm("admin", totpCode.trim()), "2FA включена").then(() => { setTotpUri(null); setTotpCode(""); refresh(); }).catch(() => undefined)}>
              Подтвердить
            </Button>
          </div>
        )}
        {enabled && (
          <div className="flex max-w-sm flex-col gap-3">
            <Field label="Текущий пароль">
              <Input type="password" value={disPw} onChange={(e) => setDisPw(e.target.value)} />
            </Field>
            <Field label="Код 2FA">
              <Input inputMode="numeric" value={disCode} onChange={(e) => setDisCode(e.target.value)} className="font-mono tracking-[0.3em]" maxLength={8} />
            </Field>
            <Button variant="danger" disabled={busy || !disPw || !disCode} onClick={() => wrap(() => panelTotpDisable("admin", disPw, disCode.trim()), "2FA отключена").then(() => { setDisPw(""); setDisCode(""); refresh(); }).catch(() => undefined)}>
              Отключить 2FA
            </Button>
          </div>
        )}
      </Card>
    </>
  );
}
