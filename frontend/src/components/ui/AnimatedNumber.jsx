import { useEffect, useRef, useState } from "react";

// Counts up to `value` on mount / when it changes. `format` maps the running
// number to a display string (e.g. money, percent). Respects reduced-motion.
export default function AnimatedNumber({ value, format = (n) => n, duration = 700 }) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef(0);

  useEffect(() => {
    const target = Number(value) || 0;
    const start = Number(fromRef.current) || 0;
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduce || start === target) {
      fromRef.current = target;
      setDisplay(target);
      return;
    }

    const t0 = performance.now();
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / duration);
      // easeOutCubic
      const eased = 1 - Math.pow(1 - p, 3);
      const current = start + (target - start) * eased;
      setDisplay(current);
      if (p < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = target;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [value, duration]);

  return <>{format(display)}</>;
}
