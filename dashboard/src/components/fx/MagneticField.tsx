"use client";

import { useEffect, useRef } from "react";

/**
 * MagneticField — ambient canvas background of short lines ("iron filings")
 * that rotate to point at the cursor with distance falloff, brightening and
 * lengthening as it approaches. Away from the cursor they drift slowly so
 * the field never looks dead.
 *
 * NOT yet wired in. Intended use (home hero / job header):
 *
 *   <div className="relative">
 *     <MagneticField className="absolute inset-0 -z-10" />
 *     ...content...
 *   </div>
 *
 * Performance: one canvas, one rAF loop, no per-line DOM. Pauses when the
 * tab is hidden or the canvas scrolls off-screen. Honors
 * prefers-reduced-motion by rendering a single static frame.
 */

interface MagneticFieldProps {
  /** Grid pitch in px between line anchors. Lower = denser field. */
  spacing?: number;
  /** Half-length of each line at rest, in px. */
  lineLength?: number;
  /** Radius of cursor influence in px. */
  influence?: number;
  /** Resting line color as an [r, g, b] triplet. */
  baseColor?: [number, number, number];
  /** Color lines blend toward as the cursor nears (scrub teal by default). */
  accentColor?: [number, number, number];
  /** Opacity of a line at rest / fully excited. */
  restAlpha?: number;
  maxAlpha?: number;
  className?: string;
}

interface FieldPoint {
  x: number;
  y: number;
  angle: number;
  /** Per-point phase offset so idle drift doesn't move in lockstep. */
  phase: number;
}

// Stable module-level defaults. Array literals used as default parameter
// values are re-created on every call, which would otherwise make these
// props change identity on every render — tearing down and rebuilding the
// effect (and resetting pointer tracking) any time the parent re-renders.
const DEFAULT_BASE_COLOR: [number, number, number] = [80, 92, 116];
const DEFAULT_ACCENT_COLOR: [number, number, number] = [45, 224, 191];

/** Shortest signed angular distance from a to b, in (-PI, PI]. */
function angleDelta(a: number, b: number): number {
  let d = (b - a) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  return d;
}

export function MagneticField({
  spacing = 26,
  lineLength = 6,
  influence = 220,
  baseColor = DEFAULT_BASE_COLOR,
  accentColor = DEFAULT_ACCENT_COLOR,
  restAlpha = 0.28,
  maxAlpha = 0.95,
  className,
}: MagneticFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let points: FieldPoint[] = [];
    let width = 0;
    let height = 0;
    let raf = 0;
    let running = false;
    let visible = true;
    // Cursor position in canvas-local coordinates; null = cursor away.
    let pointer: { x: number; y: number } | null = null;

    function rebuild() {
      const rect = canvas!.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      // Canvas is a replaced element: without an explicit CSS size, setting
      // the width/height *attributes* (the pixel buffer, scaled for DPR)
      // also becomes its intrinsic layout size and it stops filling the
      // parent. Pin the CSS box first so the buffer resize below can't
      // feed back into layout.
      canvas!.style.width = `${width}px`;
      canvas!.style.height = `${height}px`;
      canvas!.width = Math.round(width * dpr);
      canvas!.height = Math.round(height * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Keep the grid centered and cap the point count so a huge viewport
      // never turns into a huge frame budget.
      let pitch = spacing;
      while ((width / pitch) * (height / pitch) > 4200) pitch *= 1.25;
      const cols = Math.ceil(width / pitch);
      const rows = Math.ceil(height / pitch);
      const offsetX = (width - (cols - 1) * pitch) / 2;
      const offsetY = (height - (rows - 1) * pitch) / 2;

      points = [];
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          points.push({
            x: offsetX + c * pitch,
            y: offsetY + r * pitch,
            angle: Math.random() * Math.PI * 2,
            phase: Math.random() * Math.PI * 2,
          });
        }
      }
    }

    function draw(t: number) {
      ctx!.clearRect(0, 0, width, height);
      ctx!.lineWidth = 1;
      ctx!.lineCap = "round";

      const [br, bg, bb] = baseColor;
      const [ar, ag, ab] = accentColor;

      for (const p of points) {
        let strength = 0;
        let target: number;

        if (pointer) {
          const dx = pointer.x - p.x;
          const dy = pointer.y - p.y;
          const dist = Math.hypot(dx, dy);
          if (dist < influence) {
            const n = 1 - dist / influence;
            strength = n * n * (3 - 2 * n); // smoothstep falloff
            target = Math.atan2(dy, dx);
          } else {
            target = p.phase + t * 0.00012;
          }
        } else {
          target = p.phase + t * 0.00012;
        }

        // Excited lines snap; resting lines glide.
        const ease = 0.05 + strength * 0.2;
        p.angle += angleDelta(p.angle, target!) * ease;

        const len = lineLength * (1 + strength * 1.1);
        const alpha = restAlpha + (maxAlpha - restAlpha) * strength;
        const cr = Math.round(br + (ar - br) * strength);
        const cg = Math.round(bg + (ag - bg) * strength);
        const cb = Math.round(bb + (ab - bb) * strength);

        const cos = Math.cos(p.angle) * len;
        const sin = Math.sin(p.angle) * len;
        ctx!.strokeStyle = `rgba(${cr},${cg},${cb},${alpha})`;
        ctx!.beginPath();
        ctx!.moveTo(p.x - cos, p.y - sin);
        ctx!.lineTo(p.x + cos, p.y + sin);
        ctx!.stroke();
      }
    }

    function frame(t: number) {
      if (!running) return;
      draw(t);
      raf = requestAnimationFrame(frame);
    }

    function start() {
      if (running || reducedMotion || !visible || document.hidden) return;
      running = true;
      raf = requestAnimationFrame(frame);
    }

    function stop() {
      running = false;
      cancelAnimationFrame(raf);
    }

    function onPointerMove(event: PointerEvent) {
      const rect = canvas!.getBoundingClientRect();
      pointer = { x: event.clientX - rect.x, y: event.clientY - rect.y };
    }
    function onPointerLeave() {
      pointer = null;
    }
    function onVisibility() {
      if (document.hidden) stop();
      else start();
    }

    const resizeObserver = new ResizeObserver(() => {
      rebuild();
      if (reducedMotion) draw(0);
    });
    resizeObserver.observe(canvas);

    const intersectionObserver = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) start();
      else stop();
    });
    intersectionObserver.observe(canvas);

    rebuild();
    if (reducedMotion) {
      draw(0); // static field, no loop, no pointer chasing
    } else {
      window.addEventListener("pointermove", onPointerMove, { passive: true });
      document.documentElement.addEventListener("pointerleave", onPointerLeave);
      document.addEventListener("visibilitychange", onVisibility);
      start();
    }

    return () => {
      stop();
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      window.removeEventListener("pointermove", onPointerMove);
      document.documentElement.removeEventListener("pointerleave", onPointerLeave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [spacing, lineLength, influence, baseColor, accentColor, restAlpha, maxAlpha]);

  return <canvas ref={canvasRef} className={`block h-full w-full ${className ?? ""}`} aria-hidden="true" />;
}
