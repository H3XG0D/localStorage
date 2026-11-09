import { useEffect, useState } from "react";
import { Camera, CheckCircle2, KeyRound, Link2, ShieldCheck, Trash2, Upload, UserRound, type LucideIcon } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { panelChangePassword, panelTotpConfirm, panelTotpDisable, panelTotpSetup } from "@/panel/lib/panelAuth";
import {
  aiTelegramBindLink,
  aiTelegramDigest,
  aiTelegramStatus,
  aiTelegramUnbind,
  deleteAvatar,
  uploadAvatar,
  type AiTelegramStatus,
} from "@/panel/lib/operatorApi";
import { usePanelSession } from "@/panel/lib/panelSession";
import { Badge, Button, Card, Field, Input, PageHeader } from "@/panel/ui/primitives";

export function OperatorProfile() {
  const { account, refresh } = usePanelSession();
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [totpUri, setTotpUri] = useState<string | null>(null);
  const [totpSecret, setTotpSecret] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [disPw, setDisPw] = useState("");
  const [disCode, setDisCode] = useState("");
  const [tg, setTg] = useState<AiTelegramStatus | null>(null);
  const [bindLink, setBindLink] = useState<string | null>(null);
  const [bindCmd, setBindCmd] = useState<string | null>(null);
  const [digestHour, setDigestHour] = useState(10);
  const enabled = !!account?.totp_enabled;
  const displayName = String(account?.display_name || account?.username || "Оператор");
  const username = account?.username ? `@${account.username}` : "Логин не указан";
  const avatarUrl = typeof account?.avatar_url === "string" ? account.avatar_url : null;
  const roles = Array.isArray(account?.operator_roles)
    ? account.operator_roles
    : [account?.operator_role || "client"];

  useEffect(() => {
    aiTelegramStatus()
      .then((s) => {
        setTg(s);
        setDigestHour(s.digest_hour ?? 10);
      })
      .catch(() => undefined);
  }, []);

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
      <PageHeader title="Профиль оператора" subtitle="Учетная запись и безопасность" />

      <Card className="overflow-hidden p-0">
        <div className="border-b border-[var(--border)] bg-[var(--bg-elevated)]/60 p-5 sm:p-6">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-4">
              {avatarUrl ? (
                <img src={avatarUrl} alt="" className="size-20 shrink-0 rounded-[var(--radius-lg)] border border-[var(--border-strong)] object-cover shadow-[var(--shadow)]" />
              ) : (
                <div className="flex size-20 shrink-0 items-center justify-center rounded-[var(--radius-lg)] border border-[var(--border-strong)] bg-[var(--bg-overlay)] text-2xl font-bold text-[var(--text-secondary)]">
                  {displayName.slice(0, 2).toUpperCase()}
                </div>
              )}
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="m-0 truncate text-[18px] font-bold tracking-tight">{displayName}</h2>
                  <span className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--green)]"><span className="size-1.5 rounded-full bg-[var(--green)]" /> Активен</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-[var(--text-muted)]">
                  <span className="font-mono">{username}</span>
                  <span>ID {String(account?.id ?? "—")}</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {roles.map((role) => <span key={role} className="rounded-full border border-[var(--blue)]/30 bg-[var(--blue-bg)] px-2 py-0.5 text-[10px] font-semibold text-[var(--blue)]">{role === "finance" ? "Финансы" : "Клиент"}</span>)}
                </div>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <label className="inline-flex h-8 cursor-pointer items-center justify-center gap-2 rounded-[var(--radius)] bg-[var(--text-primary)] px-3 text-[12.5px] font-medium text-[var(--text-inverse)] transition-colors hover:bg-[var(--accent-hover)] has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--accent)]">
                <Upload className="size-3.5" />
                Загрузить фото
                <input
                  type="file"
                  accept="image/*"
                  className="sr-only"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) wrap(() => uploadAvatar(f), "Аватар обновлён").then(refresh).catch(() => undefined);
                  }}
                />
              </label>
              {avatarUrl && <Button variant="ghost" size="sm" disabled={busy} onClick={() => wrap(() => deleteAvatar(), "Аватар удалён").then(refresh).catch(() => undefined)}><Trash2 className="size-3.5" /> Удалить</Button>}
            </div>
          </div>
        </div>
        <div className="grid gap-3 p-5 sm:grid-cols-3 sm:p-6">
          <ProfileMeta icon={UserRound} label="Учетная запись" value={username} />
          <ProfileMeta icon={Camera} label="Профильное фото" value={avatarUrl ? "Загружено" : "Не загружено"} tone={avatarUrl ? "green" : "default"} />
          <ProfileMeta icon={ShieldCheck} label="2FA защита" value={enabled ? "Включена" : "Выключена"} tone={enabled ? "green" : "yellow"} />
        </div>
      </Card>

      <Card>
        <SectionHeading
          icon={Link2}
          title="Telegram и дайджест Ops AI"
          description="Привяжите бота — раз в сутки придёт сводка по задачам и памяти проекта. В чате AI можно писать «запомни: …»."
          status={tg?.telegram_linked ? "Привязан" : "Не привязан"}
          statusTone={tg?.telegram_linked ? "green" : "yellow"}
        />
        <div className="flex flex-col gap-3">
          {tg?.telegram_linked ? (
            <div className="text-[12.5px] text-[var(--text-secondary)]">
              Telegram ID: <span className="font-mono">{tg.telegram_user_id}</span>
            </div>
          ) : (
            <div className="text-[12.5px] text-[var(--text-muted)]">Ссылка действует 2 часа.</div>
          )}
          <div className="flex flex-wrap gap-2">
            {!tg?.telegram_linked && (
              <Button
                variant="primary"
                disabled={busy}
                onClick={() =>
                  wrap(async () => {
                    const r = await aiTelegramBindLink();
                    setBindLink(r.deep_link);
                    setBindCmd(r.command);
                    setTg(await aiTelegramStatus());
                  }, "Ссылка готова").catch(() => undefined)
                }
              >
                <Link2 className="size-3.5" /> Получить ссылку
              </Button>
            )}
            {tg?.telegram_linked && (
              <Button
                variant="danger"
                disabled={busy}
                onClick={() =>
                  wrap(async () => {
                    setTg(await aiTelegramUnbind());
                    setBindLink(null);
                    setBindCmd(null);
                  }, "Telegram отвязан").catch(() => undefined)
                }
              >
                Отвязать
              </Button>
            )}
          </div>
          {bindLink && (
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-[12px]">
              <a href={bindLink} target="_blank" rel="noreferrer" className="break-all text-[var(--blue)] underline">
                {bindLink}
              </a>
              {bindCmd && <div className="mt-2 font-mono text-[var(--text-muted)]">или в боте: {bindCmd}</div>}
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Дайджест">
              <label className="flex h-9 items-center gap-2 text-[13px]">
                <input
                  type="checkbox"
                  checked={!!tg?.digest_enabled}
                  disabled={busy || !tg}
                  onChange={(e) => {
                    const on = e.target.checked;
                    wrap(async () => {
                      setTg(await aiTelegramDigest({ enabled: on }));
                    }, on ? "Дайджест включён" : "Дайджест выключен").catch(() => undefined);
                  }}
                />
                Присылать ежедневно
              </label>
            </Field>
            <Field label="Час (МСК)">
              <Input
                type="number"
                min={0}
                max={23}
                value={digestHour}
                disabled={busy || !tg}
                onChange={(e) => setDigestHour(Number(e.target.value))}
                onBlur={() => {
                  if (!tg || digestHour === tg.digest_hour) return;
                  wrap(async () => {
                    setTg(await aiTelegramDigest({ hour: digestHour }));
                  }, "Час сохранён").catch(() => undefined);
                }}
              />
            </Field>
          </div>
        </div>
      </Card>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card>
          <SectionHeading icon={KeyRound} title="Смена пароля" description="Обновите пароль для входа в панель." />
          <div className="flex flex-col gap-3">
            <Field label="Текущий пароль">
              <Input type="password" value={curPw} onChange={(e) => setCurPw(e.target.value)} />
            </Field>
            <Field label="Новый пароль">
              <Input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="Минимум 6 символов" />
            </Field>
            <Button variant="primary" disabled={busy || !curPw || newPw.length < 6} onClick={() => wrap(() => panelChangePassword("operator", curPw, newPw), "Пароль изменён").then(() => { setCurPw(""); setNewPw(""); }).catch(() => undefined)}>
              <KeyRound className="size-3.5" /> Сохранить пароль
            </Button>
          </div>
        </Card>

        <Card>
          <SectionHeading icon={ShieldCheck} title="Двухфакторная аутентификация" description={enabled ? "Вход дополнительно защищён кодом из приложения." : "Добавьте второй шаг защиты для входа."} status={enabled ? "Включена" : "Выключена"} statusTone={enabled ? "green" : "yellow"} />
          {!enabled && !totpUri && (
            <Button variant="secondary" disabled={busy} onClick={() => wrap(async () => {
              const r = await panelTotpSetup("operator");
              setTotpUri(r.uri);
              setTotpSecret(r.secret);
            }, "Отсканируйте секрет").catch(() => undefined)}>
              <ShieldCheck className="size-3.5" /> Настроить 2FA
            </Button>
          )}
          {!enabled && totpUri && (
            <div className="flex flex-col gap-3">
              <div className="rounded-[var(--radius)] border border-[var(--blue)]/30 bg-[var(--blue-bg)] p-3 text-[12px]">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--blue)]">Секрет для приложения</div>
                <span className="select-all break-all font-mono text-[var(--text-primary)]">{totpSecret}</span>
              </div>
              <Field label="Код из приложения">
                <Input inputMode="numeric" value={totpCode} onChange={(e) => setTotpCode(e.target.value)} className="font-mono tracking-[0.3em]" maxLength={8} />
              </Field>
              <Button variant="primary" disabled={busy || totpCode.length < 6} onClick={() => wrap(() => panelTotpConfirm("operator", totpCode.trim()), "2FA включена").then(() => { setTotpUri(null); setTotpCode(""); refresh(); }).catch(() => undefined)}>
                <CheckCircle2 className="size-3.5" /> Подтвердить 2FA
              </Button>
            </div>
          )}
          {enabled && (
            <div className="flex flex-col gap-3">
              <Field label="Текущий пароль">
                <Input type="password" value={disPw} onChange={(e) => setDisPw(e.target.value)} />
              </Field>
              <Field label="Код 2FA">
                <Input inputMode="numeric" value={disCode} onChange={(e) => setDisCode(e.target.value)} className="font-mono tracking-[0.3em]" maxLength={8} />
              </Field>
              <Button variant="danger" disabled={busy || !disPw || !disCode} onClick={() => wrap(() => panelTotpDisable("operator", disPw, disCode.trim()), "2FA отключена").then(() => { setDisPw(""); setDisCode(""); refresh(); }).catch(() => undefined)}>
                <ShieldCheck className="size-3.5" /> Отключить 2FA
              </Button>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function SectionHeading({ icon: Icon, title, description, status, statusTone = "default" }: { icon: LucideIcon; title: string; description: string; status?: string; statusTone?: "default" | "green" | "yellow" }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-2.5">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[var(--radius)] bg-[var(--bg-elevated)] text-[var(--blue)]"><Icon className="size-4" /></span>
        <div className="min-w-0">
          <div className="text-[13.5px] font-semibold">{title}</div>
          <div className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">{description}</div>
        </div>
      </div>
      {status && <Badge tone={statusTone}>{status}</Badge>}
    </div>
  );
}

function ProfileMeta({ icon: Icon, label, value, tone = "default" }: { icon: LucideIcon; label: string; value: string; tone?: "default" | "green" | "yellow" }) {
  return (
    <div className="flex min-w-0 items-center gap-2.5 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2.5">
      <Icon className={`size-4 shrink-0 ${tone === "green" ? "text-[var(--green)]" : tone === "yellow" ? "text-[var(--yellow)]" : "text-[var(--text-muted)]"}`} />
      <div className="min-w-0">
        <div className="truncate text-[10px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
        <div className="truncate text-[12px] font-medium text-[var(--text-primary)]">{value}</div>
      </div>
    </div>
  );
}
