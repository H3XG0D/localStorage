import type { ReactNode } from "react";
import type { V2MyRoundResult } from "./v2RoundResult";

export function CasinoRoundResult({
  result,
  compact = false,
  children,
}: {
  result: V2MyRoundResult | null;
  compact?: boolean;
  children?: ReactNode;
}) {
  if (!result) return null;
  const tone = result.kind === "win" ? " is-win" : result.kind === "loss" ? " is-lose" : result.kind === "tie" ? " is-tie" : "";
  return (
    <div
      className={`casino-round-result${tone}${compact ? " is-compact" : ""}`}
      data-casino-v2-round-result={result.kind}
    >
      <strong>{result.title}</strong>
      <p className="casino-round-result-amount">{result.signedLabel}</p>
      <p>{result.detail}</p>
      {children ? <div className="casino-round-result-actions">{children}</div> : null}
    </div>
  );
}
