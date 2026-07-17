"use client";

import { useRef } from "react";

/**
 * GlowCard — panel whose border catches a soft teal light that follows the
 * cursor, like an instrument tray under the operating lamp. Replaces the
 * plain `rounded-xl border border-neutral-800 bg-neutral-900/60` panels.
 *
 * NOT yet wired in. Requires src/styles/theme.css tokens.
 *
 * The glow is a masked radial gradient on an overlay, so it never affects
 * layout and costs nothing when the cursor is elsewhere.
 */
export function GlowCard({
  children,
  className = "",
  style,
}: {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  const ref = useRef<HTMLDivElement>(null);

  function onPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty("--gx", `${event.clientX - rect.x}px`);
    el.style.setProperty("--gy", `${event.clientY - rect.y}px`);
  }

  return (
    <div
      ref={ref}
      onPointerMove={onPointerMove}
      style={style}
      className={`group relative rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface-1)] transition-colors duration-[var(--dur-base)] ${className}`}
    >
      {/* Border light: gradient overlay clipped to a 1px ring via mask */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-0 transition-opacity duration-300 group-hover:opacity-100 motion-reduce:hidden"
        style={{
          background:
            "radial-gradient(220px circle at var(--gx, 50%) var(--gy, 50%), rgba(45, 224, 191, 0.5), transparent 70%)",
          padding: 1,
          mask: "linear-gradient(#000 0 0) content-box exclude, linear-gradient(#000 0 0)",
          WebkitMask:
            "linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)",
          WebkitMaskComposite: "xor",
        }}
      />
      {/* Faint interior wash so the light feels like it lands on the surface */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-0 transition-opacity duration-300 group-hover:opacity-100 motion-reduce:hidden"
        style={{
          background:
            "radial-gradient(320px circle at var(--gx, 50%) var(--gy, 50%), rgba(45, 224, 191, 0.05), transparent 70%)",
        }}
      />
      {children}
    </div>
  );
}
