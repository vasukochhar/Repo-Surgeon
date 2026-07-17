"use client";

import { useEffect, useRef, useState } from "react";
import { DUR, easeOutExpo } from "@/lib/motion";

/**
 * AnimatedNumber — counts up to `value` the first time it enters the
 * viewport, then tracks later value changes by animating from the previous
 * value. For Scout vitals, test counts, and score stats.
 *
 * NOT yet wired in. Renders the final value immediately under
 * prefers-reduced-motion; always renders tabular figures so columns of
 * stats don't wobble while counting.
 */
export function AnimatedNumber({
  value,
  duration = DUR.entrance,
  suffix = "",
  className = "",
}: {
  value: number;
  duration?: number;
  suffix?: string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const previous = useRef(0);
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      previous.current = value;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot sync with a media query unavailable during SSR
      setDisplay(value);
      return;
    }

    let raf = 0;
    const from = previous.current;
    previous.current = value;

    const run = () => {
      const startedAt = performance.now();
      const tick = (now: number) => {
        const t = Math.min((now - startedAt) / duration, 1);
        setDisplay(Math.round(from + (value - from) * easeOutExpo(t)));
        if (t < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    };

    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        observer.disconnect();
        run();
      }
    });
    observer.observe(el);

    return () => {
      observer.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [value, duration]);

  return (
    <span ref={ref} className={className} style={{ fontVariantNumeric: "tabular-nums" }}>
      {display}
      {suffix}
    </span>
  );
}
