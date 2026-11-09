// Scroll-reveal wrapper. Fades + lifts content into view once (apple-design §4:
// critically damped, no bounce). Respects prefers-reduced-motion via a plain
// opacity transition (Framer Motion honours the OS setting through MotionConfig,
// but we also keep the movement small so it never reads as vestibular).
import { motion } from "framer-motion";
import type { ReactNode } from "react";

export function Reveal({
  children,
  delay = 0,
  y = 12,
  className,
}: {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ type: "spring", bounce: 0, duration: 0.5, delay }}
      className={className}
    >
      {children}
    </motion.div>
  );
}
