import type { JobState } from "@/lib/types";

const RUNNING: JobState[] = [
  "scouting",
  "researching",
  "planning",
  "operating",
  "reviewing",
  "watching_ci",
];

type Kind = "queued" | "running" | "done" | "needs_human" | "failed";

const STYLES: Record<Kind, string> = {
  queued: "bg-[var(--surface-2)] text-[var(--text-muted)]",
  running: "bg-[var(--accent-dim)] text-[var(--accent-bright)] ring-1 ring-[var(--accent)]/30",
  done: "bg-[var(--ok)]/15 text-[var(--ok)] ring-1 ring-[var(--ok)]/30",
  needs_human: "bg-[var(--warn)]/15 text-[var(--warn)] ring-1 ring-[var(--warn)]/30",
  failed: "bg-[var(--danger)]/15 text-[var(--danger)] ring-1 ring-[var(--danger)]/30",
};

const DOT_STYLES: Record<Kind, string> = {
  queued: "bg-[var(--text-faint)]",
  running: "dot-live",
  done: "bg-[var(--ok)]",
  needs_human: "bg-[var(--warn)]",
  failed: "bg-[var(--danger)]",
};

export function StateBadge({ state }: { state: JobState }) {
  const key: Kind =
    state === "queued"
      ? "queued"
      : RUNNING.includes(state)
        ? "running"
        : state === "done"
          ? "done"
          : state === "needs_human"
            ? "needs_human"
            : "failed";
  const label = state.replace(/_/g, " ");
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STYLES[key]}`}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT_STYLES[key]}`} />
      {label}
    </span>
  );
}
