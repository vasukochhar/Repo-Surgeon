"use client";

import { useEffect, useState } from "react";

/**
 * Motion system — single source of truth for durations and easings.
 * Mirrors the CSS custom properties in src/styles/theme.css; use these
 * constants when animating from JS (rAF counters, Web Animations API)
 * so JS-driven and CSS-driven motion feel identical.
 *
 * NOT yet wired in.
 */

export const EASE_OUT = "cubic-bezier(0.22, 1, 0.36, 1)";
export const EASE_SPRING = "cubic-bezier(0.34, 1.4, 0.64, 1)";

export const DUR = {
  fast: 150,
  base: 240,
  slow: 420,
  entrance: 600,
} as const;

/** easeOutExpo for rAF-driven animation (AnimatedNumber, progress fills). */
export function easeOutExpo(t: number): number {
  return t >= 1 ? 1 : 1 - Math.pow(2, -10 * t);
}

/**
 * Entrance stagger for a list: style={{ animationDelay: staggerDelay(i) }}
 * Caps the total delay so long lists don't take seconds to settle.
 */
export function staggerDelay(index: number, stepMs = 60, maxMs = 480): string {
  return `${Math.min(index * stepMs, maxMs)}ms`;
}

/** Reactive prefers-reduced-motion. SSR-safe (false on first render). */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing with a browser API unavailable during SSR
    setReduced(query.matches);
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return reduced;
}
