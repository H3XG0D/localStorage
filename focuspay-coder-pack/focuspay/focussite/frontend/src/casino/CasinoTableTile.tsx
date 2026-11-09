import type { ReactNode } from "react";
import { CasinoStartCountdown } from "./CasinoStartCountdown";

export function CasinoTableTile({
  id,
  title,
  meta,
  status,
  seated,
  countdownEndsAt,
  countdownLabel,
  onOpen,
  actions,
  children,
  layout = "grid",
}: {
  id?: string;
  title: ReactNode;
  meta?: ReactNode;
  status?: ReactNode;
  seated?: boolean;
  countdownEndsAt?: string | null;
  countdownLabel?: string;
  onOpen?: () => void;
  actions?: ReactNode;
  children: ReactNode;
  layout?: "grid" | "page";
}) {
  return (
    <article
      className={`casino-table-tile${seated ? " is-mine" : ""}${layout === "page" ? " is-page" : ""}`}
      data-casino-table-tile={id || ""}
    >
      <header className="casino-table-tile-head">
        {onOpen ? (
          <button type="button" className="casino-table-tile-title" onClick={onOpen}>
            {title}
          </button>
        ) : (
          <strong className="casino-table-tile-title">{title}</strong>
        )}
        {meta ? <span className="casino-table-tile-meta">{meta}</span> : null}
        {status ? <span className="casino-table-tile-status">{status}</span> : null}
      </header>
      <div className="casino-table-tile-stage">
        {children}
        <CasinoStartCountdown endsAt={countdownEndsAt} label={countdownLabel} />
      </div>
      {actions ? <footer className="casino-table-tile-actions">{actions}</footer> : null}
    </article>
  );
}
