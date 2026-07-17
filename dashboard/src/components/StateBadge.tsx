import type { JobState } from "@/lib/types";

const RUNNING: JobState[] = [
  "scouting",
  "researching",
  "planning",
  "operating",
  "reviewing",
  "watching_ci",
];

const STYLES: Record<string, string> = {
  queued: "bg-neutral-700 text-neutral-200",
  running: "bg-blue-600/20 text-blue-300 ring-1 ring-blue-500/40 animate-pulse",
  done: "bg-emerald-600/20 text-emerald-300 ring-1 ring-emerald-500/40",
  needs_human: "bg-amber-600/20 text-amber-300 ring-1 ring-amber-500/40",
  failed: "bg-red-600/20 text-red-300 ring-1 ring-red-500/40",
};

export function StateBadge({ state }: { state: JobState }) {
  const key = state === "queued" ? "queued"
    : RUNNING.includes(state) ? "running"
    : state === "done" ? "done"
    : state === "needs_human" ? "needs_human"
    : "failed";
  const label = state.replace(/_/g, " ");
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STYLES[key]}`}>
      {label}
    </span>
  );
}
