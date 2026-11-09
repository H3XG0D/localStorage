// Light/dark toggle. Icon cross-fades + springs on swap (apple-design §4:
// critically-damped, no gratuitous bounce). Press feedback is instant.
import { AnimatePresence, motion } from "framer-motion";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Светлая тема" : "Тёмная тема"}
      aria-pressed={isDark}
      title={isDark ? "Светлая тема" : "Тёмная тема"}
      className={cn(
        "relative inline-flex size-9 items-center justify-center overflow-hidden rounded-lg text-muted-foreground",
        "transition-[color,background-color] duration-150 hover:bg-muted hover:text-foreground active:scale-95",
        className,
      )}
    >
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={isDark ? "moon" : "sun"}
          initial={{ opacity: 0, rotate: -90, scale: 0.6 }}
          animate={{ opacity: 1, rotate: 0, scale: 1 }}
          exit={{ opacity: 0, rotate: 90, scale: 0.6 }}
          transition={{ type: "spring", bounce: 0, duration: 0.35 }}
          className="absolute inline-flex"
        >
          {isDark ? <Moon className="size-[18px]" /> : <Sun className="size-[18px]" />}
        </motion.span>
      </AnimatePresence>
    </button>
  );
}
