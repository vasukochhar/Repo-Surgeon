"use client";

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
import type { IterationPayload } from "@/lib/types";

export default function JobPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const { job, events, connected, notFound } = useJobEvents(jobId);

  if (notFound) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="text-2xl font-semibold">Job not found</h1>
        <p className="text-neutral-500">
          This job doesn&apos;t exist &mdash; it may have been created before the backend last restarted.
        </p>
        <Link href="/" className="text-sm text-blue-400 hover:underline">
          Back to home
        </Link>
      </main>
    );
  }

  if (!job) {
    return (
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-6 py-10">
        <div className="h-8 w-64 animate-pulse rounded bg-neutral-900" />
        <div className="h-24 animate-pulse rounded-xl bg-neutral-900" />
        <div className="h-48 animate-pulse rounded-xl bg-neutral-900" />
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
  const isTerminal = job.state === "done" || job.state === "needs_human" || job.state === "failed";

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-6 py-10">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold text-neutral-100">{job.repo_url}</p>
            <p className="font-mono text-xs text-neutral-500">{job.id}</p>
          </div>
          <div className="flex items-center gap-2">
            {!connected && !isTerminal && (
              <span className="rounded-full bg-neutral-800 px-2.5 py-0.5 text-xs text-neutral-400">reconnecting…</span>
            )}
            <StateBadge state={job.state} />
          </div>
        </div>
        {job.error && (
          <div className="rounded-lg border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-300">
            {job.error}
          </div>
        )}
      </header>

      <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
        <PipelineStepper jobState={job.state} events={events} />
      </div>

      {job.profile && <ScoutSummary profile={job.profile} />}
      {job.plan && <PlanTable plan={job.plan} />}

      {job.plan && job.plan.items.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">Operations</h2>
          {job.plan.items.map((item) => (
            <ItemCard
              key={item.id}
              item={item}
              iterations={iterationsByItem.get(item.id) ?? []}
              result={resultByItem.get(item.id)}
            />
          ))}
        </div>
      )}

      <PRPanel prs={job.prs} />

      <EventLog events={events} />
    </main>
  );
}
