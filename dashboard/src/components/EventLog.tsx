"use client";

import { useEffect, useRef, useState } from "react";
import type { PipelineEvent } from "@/lib/types";

function summarizePayload(event: PipelineEvent): string {
  const payload = event.payload ?? {};
  if (event.type === "iteration") {
    return `item=${payload.item_id} attempt=${payload.iteration} passed=${payload.passed}`;
  }
  if (event.type === "failed" && payload.error) {
    return String(payload.error);
  }
  return "";
}

const TYPE_COLOR: Record<string, string> = {
  started: "text-[var(--info)]",
  completed: "text-[var(--ok)]",
  failed: "text-[var(--danger)]",
  iteration: "text-[var(--accent-bright)]",
};

export function EventLog({ events, connected = true }: { events: PipelineEvent[]; connected?: boolean }) {
  const [open, setOpen] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && autoScroll) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [events, open, autoScroll]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setAutoScroll(atBottom);
  }

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface-1)]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between px-5 py-3 text-sm font-medium text-[var(--text-muted)]"
      >
        <span className="eyebrow">Live event log ({events.length})</span>
        <span className="text-[var(--text-faint)]">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="relative">
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="relative max-h-72 overflow-y-auto border-t border-[var(--border)] bg-[var(--bg)] px-5 py-3 font-mono text-[11px] leading-6 text-[var(--text-muted)]"
            style={{
              backgroundImage:
                "repeating-linear-gradient(0deg, rgba(255,255,255,0.02) 0px, rgba(255,255,255,0.02) 1px, transparent 1px, transparent 3px)",
            }}
          >
            {events.length === 0 ? (
              <p className="text-[var(--text-faint)]">Waiting for events…</p>
            ) : (
              events.map((event, index) => {
                const summary = summarizePayload(event);
                const isLast = index === events.length - 1;
                return (
                  <div key={index} className="rise-in" style={{ animationDuration: "220ms" }}>
                    <span className="text-[var(--text-faint)]">[{new Date(event.ts).toLocaleTimeString()}]</span>{" "}
                    <span className={TYPE_COLOR[event.type] ?? "text-[var(--text)]"}>{event.stage}</span> {event.type}
                    {summary && <span className="text-[var(--text-faint)]"> — {summary}</span>}
                    {isLast && connected && (
                      <span aria-hidden="true" className="ml-1 inline-block h-3 w-1.5 translate-y-0.5 bg-[var(--accent)]" style={{ animation: "blink 1s step-end infinite" }} />
                    )}
                  </div>
                );
              })
            )}
            <div ref={bottomRef} />
          </div>
          {!autoScroll && events.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setAutoScroll(true);
                bottomRef.current?.scrollIntoView({ block: "end" });
              }}
              className="absolute bottom-3 right-5 rounded-full bg-[var(--accent)] px-3 py-1 text-[11px] font-medium text-[#04150f] shadow-[var(--shadow-lift)]"
            >
              ↓ new events
            </button>
          )}
        </div>
      )}
    </div>
  );
}
