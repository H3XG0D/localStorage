// Spring count-up number. Animates from the current on-screen value to the new
// target (apple-design §3/§4: start from the presentation value, spring, no
// bounce). Falls back to the static value under reduced motion.
import { useEffect, useRef, useState } from "react";
import { animate, useReducedMotion } from "framer-motion";

export function AnimatedNumber({
  value,
  maximumFractionDigits = 0,
  className,
}: {
  value: number;
  maximumFractionDigits?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(value);
  const prev = useRef(value);

  useEffect(() => {
    if (reduce || prev.current === value) {
      setDisplay(value);
      prev.current = value;
      return;
    }
    const controls = animate(prev.current, value, {
      type: "spring",
      bounce: 0,
      duration: 0.5,
      onUpdate: (v) => setDisplay(v),
    });
    prev.current = value;
    return () => controls.stop();
  }, [value, reduce]);

  return (
    <span className={className}>
      {display.toLocaleString("ru-RU", { maximumFractionDigits })}
    </span>
  );
}
