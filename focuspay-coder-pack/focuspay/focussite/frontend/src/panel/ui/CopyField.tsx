import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";

/** One-click copy field with a value + label. */
export function CopyField({ label, value }: { label: string; value: string }) {
  const [done, setDone] = useState(false);
  if (!value) return null;
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(value).then(
          () => {
            setDone(true);
            window.setTimeout(() => setDone(false), 1200);
          },
          () => toast.error("Не удалось скопировать"),
        );
      }}
      className="group flex w-full items-center justify-between gap-3 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5 text-left transition-colors hover:bg-[var(--bg-overlay)]"
    >
      <span className="min-w-0">
        <span className="block text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</span>
        <span className="block break-all font-mono text-[13px]">{value}</span>
      </span>
      {done ? <Check className="size-4 shrink-0 text-[var(--green)]" /> : <Copy className="size-4 shrink-0 text-[var(--text-muted)] group-hover:text-[var(--text-primary)]" />}
    </button>
  );
}
