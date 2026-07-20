"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useJobLogs } from "@/hooks/useJobLogs";

const LEVEL_COLOR: Record<string, string> = {
  INFO: "text-[var(--text-muted)]",
  WARNING: "text-[var(--warn)]",
  ERROR: "text-[var(--danger)]",
  DEBUG: "text-[var(--text-faint)]",
};

function formatTs(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000);
  return d.toTimeString().slice(0, 8) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

export function LiveLogPanel({ jobId }: { jobId: string }) {
  const { logs, connected } = useJobLogs(jobId);
  const [open, setOpen] = useState(true);
  const [filter, setFilter] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    if (!filter.trim()) return logs;
    const needle = filter.toLowerCase();
    return logs.filter((entry) => entry.message.toLowerCase().includes(needle));
  }, [logs, filter]);

  useEffect(() => {
    if (open && autoScroll) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [filtered, open, autoScroll]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
  }

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface-1)]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between px-5 py-3 text-sm font-medium text-[var(--text-muted)]"
      >
        <span className="eyebrow">
          Backend log ({logs.length}){!connected && <span className="ml-2 text-[var(--warn)]">reconnecting…</span>}
        </span>
        <span className="text-[var(--text-faint)]">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="relative">
          <div className="flex items-center gap-2 border-t border-[var(--border)] px-5 py-2">
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="filter (e.g. scanner, error, requests)"
              className="w-full rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1 text-xs text-[var(--text)] placeholder:text-[var(--text-faint)] focus:border-[var(--accent)] focus:outline-none"
            />
          </div>
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="max-h-96 overflow-y-auto border-t border-[var(--border)] bg-[var(--bg)] px-5 py-3 font-mono text-[11px] leading-6 text-[var(--text-muted)]"
          >
            {filtered.length === 0 ? (
              <p className="text-[var(--text-faint)]">
                {logs.length === 0 ? "Waiting for backend log lines…" : "No lines match the filter."}
              </p>
            ) : (
              filtered.map((entry) => (
                <div key={entry.seq} className="whitespace-pre-wrap break-words">
                  <span className="text-[var(--text-faint)]">[{formatTs(entry.ts)}]</span>{" "}
                  <span className="text-[var(--accent-bright)]">{entry.logger.replace("repo_surgeon.", "")}</span>{" "}
                  <span className={LEVEL_COLOR[entry.level] ?? "text-[var(--text)]"}>{entry.message}</span>
                </div>
              ))
            )}
            <div ref={bottomRef} />
          </div>
          {!autoScroll && filtered.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setAutoScroll(true);
                bottomRef.current?.scrollIntoView({ block: "end" });
              }}
              className="absolute bottom-3 right-5 rounded-full bg-[var(--accent)] px-3 py-1 text-[11px] font-medium text-[#04150f] shadow-[var(--shadow-lift)]"
            >
              ↓ new lines
            </button>
          )}
        </div>
      )}
    </div>
  );
}
