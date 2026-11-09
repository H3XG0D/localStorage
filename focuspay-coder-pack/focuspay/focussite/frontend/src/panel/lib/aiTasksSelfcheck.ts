/** SAST self-check helpers for Admin · /x8/ai-tasks (alarm ≠ vulnerability finding). */

export const SELFCHECK_ALARM_STATUSES = ["failed", "skipped", "unavailable", "error"] as const;

export function isSelfcheckAlarm(status?: string | null): boolean {
  const s = String(status || "").toLowerCase();
  return (SELFCHECK_ALARM_STATUSES as readonly string[]).includes(s);
}

export function isCheckStatusFinding(item: {
  kind?: string;
  status?: string;
  text?: string;
} | null | undefined): boolean {
  if (!item) return false;
  if (String(item.kind || "").toLowerCase() === "selfcheck") return true;
  const st = String(item.status || "").toLowerCase();
  if (st === "skipped" || st === "unavailable") return true;
  return /^(bandit|pip-audit|pip_audit)(\[[^\]]+\])?\s*:\s*(not installed|not_installed|skipped|unavailable)\s*$/i.test(
    String(item.text || ""),
  );
}

export function selfcheckBadgeTone(status?: string | null): "green" | "red" | "default" {
  const s = String(status || "").toLowerCase();
  if (s === "passed") return "green";
  if (isSelfcheckAlarm(s)) return "red";
  return "default";
}
