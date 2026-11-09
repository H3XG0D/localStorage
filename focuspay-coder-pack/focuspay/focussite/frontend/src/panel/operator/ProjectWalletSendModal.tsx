import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ExternalLink, RefreshCw, ShieldCheck, Wallet } from "lucide-react";
import { PanelApiError } from "@/panel/lib/panelApi";
import type { WalletPreview, WalletSendInput } from "@/panel/lib/operatorApi";
import { CopyField } from "@/panel/ui/CopyField";
import { Badge, Button, Input, Modal, cx } from "@/panel/ui/primitives";

const EXPLORER: Record<string, (tx: string) => string> = {
  btc: (tx) => `https://mempool.space/tx/${tx}`,
  ltc: (tx) => `https://litecoinspace.org/tx/${tx}`,
};

const CHECK_LABEL: Record<string, string> = {
  address: "Кошелёк клиента",
  address_other_client: "Адрес не принадлежит другому клиенту",
  address_operator: "Адрес не принадлежит оператору",
  address_own: "Адрес не наш собственный",
  limit_per_payout: "Лимит одной отправки",
  limit_operator_day: "Ваш лимит на сегодня",
  limit_wallet_day: "Общий лимит кошелька на сегодня",
  signer: "Кошелёк проекта на связи",
  live: "Кошелёк в боевом режиме",
  node: "Нода синхронизирована",
  balance: "Хватает баланса с комиссией",
};

const rub = (v: unknown) => `${Math.round(Number(v) || 0).toLocaleString("ru-RU")} ₽`;
const coinAmt = (v: unknown) => Number(v || 0).toLocaleString("ru-RU", { maximumFractionDigits: 8 });

function AddressView({ address }: { address: string }) {
  const head = address.slice(0, 6);
  const tail = address.length > 12 ? address.slice(-6) : "";
  const middle = address.slice(head.length, address.length - tail.length);
  return (
    <div className="break-all rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2.5 font-mono text-[13px] leading-relaxed">
      <span className="font-bold text-[var(--text-primary)]">{head}</span>
      <span className="text-[var(--text-muted)]">{middle}</span>
      <span className="font-bold text-[var(--text-primary)]">{tail}</span>
    </div>
  );
}

function Row({ label, children, tone }: { label: string; children: React.ReactNode; tone?: "red" | "yellow" }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-[13px]">
      <span className="text-[var(--text-muted)]">{label}</span>
      <span
        className={cx(
          "text-right font-mono",
          tone === "red" && "text-[var(--red)]",
          tone === "yellow" && "text-[var(--yellow)]",
        )}
      >
        {children}
      </span>
    </div>
  );
}

type Phase = "loading" | "confirm" | "sending" | "done" | "stuck" | "error";

export function ProjectWalletSendModal({
  open,
  onClose,
  loadPreview,
  send,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  loadPreview: () => Promise<WalletPreview>;
  send: (body: WalletSendInput) => Promise<{ txid?: string }>;
  onDone: (txid: string) => void;
}) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [preview, setPreview] = useState<WalletPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [txid, setTxid] = useState("");
  const [left, setLeft] = useState(0);
  const expiresAt = useRef(0);
  const loadRef = useRef(loadPreview);
  loadRef.current = loadPreview;

  const load = useCallback(async () => {
    setPhase("loading");
    setError(null);
    setCode("");
    try {
      const p = await loadRef.current();
      setPreview(p);
      expiresAt.current = Date.now() + (Number(p.expires_in) || 120) * 1000;
      setLeft(Number(p.expires_in) || 120);
      setPhase("confirm");
    } catch (e) {
      setPreview(null);
      setError(e instanceof PanelApiError ? e.message : "Не удалось подготовить отправку");
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  useEffect(() => {
    if (phase !== "confirm") return;
    const t = window.setInterval(() => setLeft(Math.max(0, Math.round((expiresAt.current - Date.now()) / 1000))), 1000);
    return () => window.clearInterval(t);
  }, [phase]);

  const expired = phase === "confirm" && left <= 0;
  const failed = (preview?.checks ?? []).filter((c) => !c.ok);
  const otherClient = failed.some((c) => c.key === "address_other_client");
  const hard = failed.filter((c) => c.key !== "address_other_client");
  const canSend =
    phase === "confirm" &&
    !!preview?.ok &&
    !!preview.preview_token &&
    !expired &&
    hard.length === 0 &&
    /^\d{6}$/.test(code);

  const doSend = async () => {
    if (!canSend || !preview?.preview_token) return;
    setPhase("sending");
    setError(null);
    try {
      const r = await send({
        preview_token: preview.preview_token,
        totp_code: code,
        allow_other_client: otherClient,
      });
      setTxid(String(r.txid ?? ""));
      setPhase("done");
    } catch (e) {
      const msg = e instanceof PanelApiError ? e.message : "Отправка не удалась";
      const status = e instanceof PanelApiError ? e.status : 0;
      setError(msg);
      setCode("");
      // 5xx: крипта могла уйти — повтор только после проверки админом.
      setPhase(status >= 500 ? "stuck" : "confirm");
    }
  };

  const close = () => {
    if (phase === "sending") return;
    if (phase === "done") onDone(txid);
    onClose();
  };

  const coin = String(preview?.coin ?? "").toUpperCase();
  const client = preview?.client;
  const clientName = client?.username || client?.first_name || (client?.user_id ? `ID ${client.user_id}` : "—");
  const explorer = EXPLORER[String(preview?.coin ?? "").toLowerCase()];

  const footer =
    phase === "done" ? (
      <Button variant="primary" onClick={close}>
        Готово
      </Button>
    ) : phase === "stuck" || phase === "error" ? (
      <>
        {phase === "error" && (
          <Button onClick={() => void load()}>
            <RefreshCw className="size-4" /> Повторить
          </Button>
        )}
        <Button onClick={close}>Закрыть</Button>
      </>
    ) : (
      <>
        <Button onClick={close} disabled={phase === "sending"}>
          Отмена
        </Button>
        {expired ? (
          <Button variant="primary" onClick={() => void load()}>
            <RefreshCw className="size-4" /> Пересчитать
          </Button>
        ) : (
          <Button variant="primary" disabled={!canSend} onClick={() => void doSend()}>
            {phase === "sending" ? "Отправляем…" : `Отправить ${coin}`}
          </Button>
        )}
      </>
    );

  return (
    <Modal open={open} onClose={close} title="Отправка с кошелька проекта" footer={footer}>
      {phase === "loading" && <div className="py-10 text-center text-sm text-[var(--text-muted)]">Считаем сумму и проверяем кошелёк…</div>}

      {phase === "error" && (
        <div className="flex gap-3 rounded-[var(--radius)] bg-[var(--red-bg)] p-4 text-[13px] text-[var(--red)]">
          <AlertTriangle className="size-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {phase === "done" && preview && (
        <div className="space-y-4 py-2 text-center">
          <CheckCircle2 className="mx-auto size-12 text-[var(--green)]" />
          <div>
            <div className="font-mono text-2xl font-extrabold">
              {coinAmt(preview.crypto_amount)} {coin}
            </div>
            <div className="text-[13px] text-[var(--text-muted)]">отправлено {clientName}, заявка закрыта</div>
          </div>
          {txid && (
            <div className="space-y-2 text-left">
              <CopyField label="Транзакция" value={txid} />
              {explorer && (
                <a
                  href={explorer(txid)}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[12px] text-[var(--text-secondary)] underline-offset-2 hover:underline"
                >
                  Открыть в эксплорере <ExternalLink className="size-3" />
                </a>
              )}
            </div>
          )}
        </div>
      )}

      {phase === "stuck" && (
        <div className="flex gap-3 rounded-[var(--radius)] bg-[var(--yellow-bg)] p-4 text-[13px] text-[var(--yellow)]">
          <AlertTriangle className="size-5 shrink-0" />
          <div className="space-y-1">
            <div className="font-semibold">Не отправляйте повторно</div>
            <div>{error}</div>
          </div>
        </div>
      )}

      {(phase === "confirm" || phase === "sending") && preview && (
        <div className="space-y-4">
          <div className="rounded-[var(--radius-lg)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-4 text-center">
            <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">Клиент получит</div>
            <div className="mt-1 font-mono text-3xl font-extrabold tabular-nums">
              {coinAmt(preview.crypto_amount)} <span className="text-[var(--text-secondary)]">{coin}</span>
            </div>
            <div className="mt-1 text-[13px] text-[var(--text-muted)]">
              заявка на {rub(preview.amount_rub)} · {clientName}
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-[12px] text-[var(--text-muted)]">
                <Wallet className="size-3.5" /> Куда
              </span>
              {Number(preview.sent_before) > 0 ? (
                <Badge tone="green">уже отправляли: {preview.sent_before}</Badge>
              ) : (
                <Badge tone="yellow">новый адрес — сверьте с клиентом</Badge>
              )}
            </div>
            <AddressView address={preview.address} />
          </div>

          <div className="divide-y divide-[var(--border)] rounded-[var(--radius)] border border-[var(--border)] px-3">
            <Row label="Комиссия сети">
              ≈ {coinAmt(preview.fee_crypto)} {coin} · {rub(preview.fee_rub)}
              {preview.fee_sat_vb ? ` · ${Number(preview.fee_sat_vb).toFixed(1)} sat/vB` : ""}
            </Row>
            <Row label="Останется в кошельке">
              {coinAmt(preview.balance_after_crypto)} {coin}
            </Row>
            {Number(preview.pending_crypto) > 0 && (
              <Row label="Ждёт подтверждения" tone="yellow">
                {coinAmt(preview.pending_crypto)} {coin}
              </Row>
            )}
            <Row label="Ваш лимит на сегодня" tone={preview.operator_left_rub < preview.amount_rub ? "red" : undefined}>
              осталось {rub(preview.operator_left_rub)}
            </Row>
          </div>

          {hard.length > 0 && (
            <div className="space-y-1 rounded-[var(--radius)] bg-[var(--red-bg)] p-3 text-[12px] text-[var(--red)]">
              <div className="font-semibold">Отправка невозможна:</div>
              {hard.map((c) => (
                <div key={c.key}>
                  · {CHECK_LABEL[c.key] ?? c.key}
                  {c.detail ? ` — ${c.detail}` : ""}
                </div>
              ))}
              {preview.pending_covers && hard.some((c) => c.key === "balance") && (
                <div className="pt-1 text-[var(--yellow)]">
                  Пополнение в пути покроет отправку — после 1 подтверждения откройте отправку заново.
                </div>
              )}
            </div>
          )}

          {otherClient && hard.length === 0 && (
            <div className="rounded-[var(--radius)] bg-[var(--yellow-bg)] p-3 text-[12px] text-[var(--yellow)]">
              Этот адрес уже есть у другого клиента. Код 2FA подтверждает отправку.
            </div>
          )}

          {preview.ok && hard.length === 0 && (
            <div className="space-y-2">
              <label className="flex items-center gap-1.5 text-[12px] text-[var(--text-muted)]" htmlFor="pw-totp">
                <ShieldCheck className="size-3.5" /> Код 2FA из приложения
              </label>
              <Input
                id="pw-totp"
                autoFocus
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                disabled={phase === "sending" || expired}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void doSend();
                }}
                className="text-center font-mono text-xl tracking-[0.5em]"
                placeholder="••••••"
              />
              <div className="flex items-center justify-between text-[11px] text-[var(--text-muted)]">
                <span>{expired ? "Окно устарело — пересчитайте" : `Сумма зафиксирована ещё ${left} с`}</span>
                <span>каждый код — одна отправка</span>
              </div>
            </div>
          )}

          {error && <div className="rounded-[var(--radius)] bg-[var(--red-bg)] p-3 text-[12px] text-[var(--red)]">{error}</div>}
        </div>
      )}
    </Modal>
  );
}
