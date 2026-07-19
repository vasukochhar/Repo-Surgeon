"use client";

import { useEffect, useRef, useState } from "react";
import { TERMINAL_STATES } from "@/lib/types";
import type { JobDetail } from "@/lib/types";

function summarize(job: JobDetail): string {
  const planned = job.plan?.items.length ?? 0;
  if (planned === 0) {
    const vulns = job.profile?.security_report.total ?? 0;
    return vulns > 0
      ? `${vulns} ${vulns === 1 ? "vulnerability" : "vulnerabilities"} found, but no actionable upgrades.`
      : "No outdated or vulnerable dependencies found — nothing to change.";
  }
  const green = job.results.filter((r) => r.status === "green").length;
  const flagged = job.results.filter((r) => r.status === "needs_human").length;
  const parts = [`${green}/${planned} upgrades green`];
  if (flagged > 0) parts.push(`${flagged} need${flagged === 1 ? "s" : ""} a human`);
  parts.push(job.prs.length === 0 ? "no PRs opened" : `${job.prs.length} PR${job.prs.length === 1 ? "" : "s"} opened`);
  return parts.join(" · ");
}

const TITLES: Record<string, string> = {
  done: "Job complete",
  needs_human: "Job finished — needs a human",
  failed: "Job failed",
};

export function CompletionToast({ job }: { job: JobDetail }) {
  const [visible, setVisible] = useState(false);
  const previousState = useRef(job.state);

  useEffect(() => {
    const wasTerminal = TERMINAL_STATES.includes(previousState.current);
    const isTerminal = TERMINAL_STATES.includes(job.state);
    previousState.current = job.state;
    if (isTerminal && !wasTerminal) {
      setVisible(true);
      const timer = setTimeout(() => setVisible(false), 12_000);
      return () => clearTimeout(timer);
    }
  }, [job.state]);

  if (!visible) return null;

  const accent = job.state === "done" ? "var(--ok)" : job.state === "failed" ? "var(--danger)" : "var(--warn)";

  return (
    <div
      role="status"
      aria-live="polite"
      className="rise-in fixed bottom-6 right-6 z-50 w-80 rounded-[var(--radius-lg)] border bg-[var(--surface-1)] p-4 shadow-xl"
      style={{ borderColor: accent }}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-semibold" style={{ color: accent }}>
          {TITLES[job.state] ?? "Job finished"}
        </p>
        <button
          type="button"
          onClick={() => setVisible(false)}
          aria-label="Dismiss"
          className="text-[var(--text-faint)] hover:text-[var(--text)]"
        >
          ✕
        </button>
      </div>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        {job.error ?? summarize(job)}
      </p>
    </div>
  );
}
