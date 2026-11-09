import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";

export function Brand({ compact = false, className }: { compact?: boolean; className?: string }) {
  return <div className={cn("flex items-center gap-2.5", className)}><div className={cn("flex shrink-0 items-center justify-center rounded-lg bg-primary p-1.5", compact ? "size-8" : "size-9")}>{/* Logo is a white-filled SVG silhouette; render via CSS mask so it inherits the theme-aware primary-foreground color instead of a baked-in white (invisible on the white badge in dark mode). */}<span className="size-full bg-primary-foreground [mask-image:url(/focuspay-logo.svg)] [mask-position:center] [mask-repeat:no-repeat] [mask-size:contain]" aria-hidden /></div><div className="leading-none"><div className="font-extrabold tracking-[-0.05em]">FocusPay</div>{!compact && <div className="mt-1 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">crypto exchange</div>}</div></div>;
}

export function ExternalMark() { return <ArrowUpRight data-icon="inline-end" />; }
