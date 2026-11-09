import { cn } from "@/lib/utils";

export function StatusDot({ label = "Система онлайн", tone = "neutral" }: { label?: string; tone?: "neutral" | "positive" | "warning" }) {
  return <span className="inline-flex items-center gap-2 text-xs text-muted-foreground"><span className={cn("size-2 rounded-full", tone === "positive" ? "bg-foreground" : tone === "warning" ? "bg-muted-foreground" : "border border-foreground/40")} />{label}</span>;
}
