import { formatRub } from "./casinoLevelCopy";
import {
  isActiveWithdrawal,
  shortRequisites,
  withdrawalCancellable,
  withdrawalPhase,
  withdrawalStatusHint,
  withdrawalStatusLabel,
  withdrawalStatusTone,
} from "./casinoWalletRules";
import type { WithdrawalRow } from "@/lib/user";

function formatWhen(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function methodTitle(row: WithdrawalRow): string {
  if (String(row.method ?? "") === "crypto") {
    const crypto = String(row.crypto ?? "крипта").toUpperCase();
    const network = String(row.network ?? "").trim();
    return network ? `${crypto} ${network}` : crypto;
  }
  return "Карта";
}

export function CasinoWithdrawalCard({
  row,
  onCancel,
  cancelling = false,
}: {
  row: WithdrawalRow;
  onCancel?: (id: number) => void;
  cancelling?: boolean;
}) {
  const phase = withdrawalPhase(row);
  const cancellable = Boolean(onCancel) && withdrawalCancellable(row);
  const hint = withdrawalStatusHint(row);
  const dest = shortRequisites(String(row.method ?? ""), String(row.requisites ?? ""));

  return (
    <article
      className="casino-wd-card"
      data-casino-wd-card=""
      data-casino-wd-phase={phase}
      data-casino-wd-active={isActiveWithdrawal(row) ? "" : undefined}
    >
      <div className="casino-wd-card-main">
        <strong>Вывод · {methodTitle(row)}</strong>
        <p className="casino-muted">
          {formatWhen(row.created_at)}
          {dest ? ` · ${dest}` : ""}
        </p>
        <p
          className="casino-status-badge casino-wd-status"
          data-casino-wd-status={phase}
          data-casino-status-tone={withdrawalStatusTone(phase)}
        >
          {withdrawalStatusLabel(row)}
        </p>
        {hint ? <p className="casino-muted">{hint}</p> : null}
      </div>
      <div className="casino-wd-card-side">
        <span className="casino-mono">−{formatRub(Number(row.amount_rub ?? 0))}</span>
        {cancellable ? (
          <button
            type="button"
            className="casino-btn casino-btn-ghost casino-wd-cancel"
            data-casino-wd-cancel=""
            disabled={cancelling}
            onClick={() => onCancel?.(row.id)}
          >
            {cancelling ? "Отмена…" : "Отменить"}
          </button>
        ) : null}
      </div>
    </article>
  );
}
