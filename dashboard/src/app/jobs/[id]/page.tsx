"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useJobEvents } from "@/hooks/useJobEvents";
import { StateBadge } from "@/components/StateBadge";
import { PipelineStepper } from "@/components/PipelineStepper";
import { ScoutSummary } from "@/components/ScoutSummary";
import { PlanTable } from "@/components/PlanTable";
import { ItemCard } from "@/components/ItemCard";
import { PRPanel } from "@/components/PRPanel";
import { EventLog } from "@/components/EventLog";
import { CompletionToast } from "@/components/CompletionToast";
import { staggerDelay } from "@/lib/motion";
import type { IterationPayload } from "@/lib/types";

function useElapsed(startedAt: number | null, stopped: boolean): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (stopped || startedAt == null) return;
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [startedAt, stopped]);
  if (startedAt == null) return "—";
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function JobPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const { job, events, connected, notFound } = useJobEvents(jobId);
  const [copied, setCopied] = useState(false);

  const firstEventTs = events.length > 0 ? new Date(events[0].ts).getTime() : null;
  const isTerminal = job ? job.state === "done" || job.state === "needs_human" || job.state === "failed" : false;
  const elapsed = useElapsed(firstEventTs, isTerminal);

  function copyJobId() {
    if (!job) return;
    void navigator.clipboard.writeText(job.id);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  if (notFound) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="text-2xl font-semibold">Job not found</h1>
        <p className="text-[var(--text-faint)]">
          This job doesn&apos;t exist &mdash; it may have been created before the backend last restarted.
        </p>
        <Link href="/" className="text-sm text-[var(--accent-bright)] hover:underline">
          Back to home
        </Link>
      </main>
    );
  }

  if (!job) {
    return (
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-6 py-10">
        <div className="h-8 w-64 animate-pulse rounded bg-[var(--surface-1)]" />
        <div className="h-24 animate-pulse rounded-[var(--radius-lg)] bg-[var(--surface-1)]" />
        <div className="h-48 animate-pulse rounded-[var(--radius-lg)] bg-[var(--surface-1)]" />
      </main>
    );
  }

  const iterationsByItem = new Map<string, IterationPayload[]>();
  for (const event of events) {
    if (event.type !== "iteration") continue;
    const payload = event.payload as unknown as IterationPayload;
    const list = iterationsByItem.get(payload.item_id) ?? [];
    list.push(payload);
    iterationsByItem.set(payload.item_id, list);
  }
  const resultByItem = new Map(job.results.map((result) => [result.item_id, result]));
  const flaggedItems = job.results.filter((r) => r.status === "needs_human");

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-6 py-10">
      <header className="sticky top-[57px] z-30 -mx-6 space-y-3 border-b border-[var(--border)] bg-[var(--surface-glass)] px-6 py-4 backdrop-blur-md">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold text-[var(--text)]">{job.repo_url}</p>
            <button
              type="button"
              onClick={copyJobId}
              className="flex items-center gap-1.5 font-mono text-xs text-[var(--text-faint)] hover:text-[var(--text-muted)]"
              title="Click to copy job id"
            >
              {job.id}
              <span className="text-[var(--accent)]">{copied ? "✓ copied" : "⧉"}</span>
            </button>
          </div>
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs text-[var(--text-faint)]" style={{ fontVariantNumeric: "tabular-nums" }}>
              {elapsed}
            </span>
            {!connected && !isTerminal && (
              <span className="rounded-full bg-[var(--surface-2)] px-2.5 py-0.5 text-xs text-[var(--text-muted)]">
                reconnecting…
              </span>
            )}
            <StateBadge state={job.state} />
          </div>
        </div>
        {job.error && (
          <div className="rounded-[var(--radius-md)] border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]">
            {job.error}
          </div>
        )}
      </header>

      {job.state === "needs_human" && flaggedItems.length > 0 && (
        <div className="rise-in rounded-[var(--radius-lg)] border border-[var(--warn)]/40 bg-[var(--warn)]/10 px-5 py-4 text-sm">
          <p className="font-medium text-[var(--warn)]">
            ⚑ {flaggedItems.length} {flaggedItems.length === 1 ? "item needs" : "items need"} a human — still failing
            after {flaggedItems[0]?.iterations ?? 5} attempts.
          </p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {flaggedItems.map((r) => (
              <li key={r.item_id}>
                <a href={`#item-${r.item_id}`} className="rounded-full bg-[var(--surface-1)] px-2.5 py-0.5 font-mono text-xs text-[var(--text-muted)] hover:text-[var(--warn)]">
                  {r.item_id}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="rise-in rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface-1)] p-5">
        <PipelineStepper jobState={job.state} events={events} />
      </div>

      {job.profile && <ScoutSummary profile={job.profile} />}
      {job.plan && <PlanTable plan={job.plan} />}

      {job.plan && job.plan.items.length > 0 && (
        <div className="space-y-4">
          <h2 className="eyebrow">Operations</h2>
          {job.plan.items.map((item, index) => (
            <div key={item.id} id={`item-${item.id}`} className="rise-in" style={{ animationDelay: staggerDelay(index) }}>
              <ItemCard
                item={item}
                iterations={iterationsByItem.get(item.id) ?? []}
                result={resultByItem.get(item.id)}
              />
            </div>
          ))}
        </div>
      )}

      <PRPanel prs={job.prs} />

      <EventLog events={events} connected={connected} />

      <CompletionToast job={job} />
    </main>
  );
}
