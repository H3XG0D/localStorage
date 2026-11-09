import { Link } from "react-router-dom";
import type { ReactNode } from "react";

export function opsClientId(value: unknown): number | null {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function opsClientPath(userId: number | string, tab?: "casino"): string {
  const id = encodeURIComponent(String(userId).trim());
  return tab === "casino" ? `/ops/client/${id}?tab=casino` : `/ops/client/${id}`;
}

export function OpsClientLink({
  userId,
  children,
  tab,
  className,
}: {
  userId: number | string | null | undefined;
  children: ReactNode;
  tab?: "casino";
  className?: string;
}) {
  const id = opsClientId(userId);
  if (id == null) return children;
  return (
    <Link
      to={opsClientPath(id, tab)}
      onClick={(event) => event.stopPropagation()}
      className={className ?? "text-[var(--blue)] underline-offset-2 hover:underline"}
      data-ops-client-link={tab ?? "exchange"}
    >
      {children}
    </Link>
  );
}
