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

export function EventLog({ events }: { events: PipelineEvent[] }) {
  const [open, setOpen] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [events, open]);

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/60">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between px-5 py-3 text-sm font-medium text-neutral-300"
      >
        <span>Live event log ({events.length})</span>
        <span className="text-neutral-500">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="max-h-72 overflow-y-auto border-t border-neutral-800 px-5 py-3 font-mono text-[11px] leading-6 text-neutral-400">
          {events.length === 0 ? (
            <p className="text-neutral-600">Waiting for events…</p>
          ) : (
            events.map((event, index) => {
              const summary = summarizePayload(event);
              return (
                <div key={index}>
                  <span className="text-neutral-600">[{new Date(event.ts).toLocaleTimeString()}]</span>{" "}
                  <span className="text-neutral-300">{event.stage}</span> {event.type}
                  {summary && <span className="text-neutral-500"> — {summary}</span>}
                </div>
              );
            })
          )}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
