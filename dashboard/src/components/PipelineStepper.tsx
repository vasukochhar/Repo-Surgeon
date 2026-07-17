import { PIPELINE_STAGES, type JobState, type PipelineEvent } from "@/lib/types";

type StepStatus = "pending" | "active" | "complete" | "failed";

function stepStatus(stage: JobState, events: PipelineEvent[], jobState: JobState): StepStatus {
  const started = events.some((event) => event.stage === stage && event.type === "started");
  const completed = events.some((event) => event.stage === stage && event.type === "completed");
  if (completed) return "complete";
  if (started) {
    if (jobState === "failed") return "failed";
    return "active";
  }
  return "pending";
}

const LABELS: Record<JobState, string> = {
  queued: "Queued",
  scouting: "Scout",
  researching: "Research",
  planning: "Plan",
  operating: "Operate",
  reviewing: "Review",
  watching_ci: "Watch CI",
  done: "Done",
  needs_human: "Needs human",
  failed: "Failed",
};

function StepNode({ status, index }: { status: StepStatus; index: number }) {
  if (status === "complete") {
    return (
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--ok)] text-[#04150a]">
        <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none">
          <path
            d="M3.5 8.5L6.5 11.5L12.5 4.5"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
            style={{
              strokeDasharray: 1,
              strokeDashoffset: 0,
              transition: "stroke-dashoffset 320ms var(--ease-out)",
            }}
          />
        </svg>
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--danger)] text-xs font-semibold text-white">
        ✕
      </div>
    );
  }
  if (status === "active") {
    return (
      <div className="dot-live flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-[#04150f]">
        {index + 1}
      </div>
    );
  }
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-[var(--text-faint)] ring-1 ring-inset ring-[var(--border-strong)]">
      {index + 1}
    </div>
  );
}

function Connector({ complete, active, vertical }: { complete: boolean; active: boolean; vertical?: boolean }) {
  const base = vertical ? "w-0.5" : "mx-1 h-0.5 w-8 shrink-0 sm:w-12";
  if (complete) return <div className={`${base} bg-[var(--ok)]`} style={vertical ? { height: 16 } : undefined} />;
  if (active) return <div className={`connector-active ${base}`} style={vertical ? { height: 16 } : undefined} />;
  return <div className={`${base} bg-[var(--border)]`} style={vertical ? { height: 16 } : undefined} />;
}

export function PipelineStepper({ jobState, events }: { jobState: JobState; events: PipelineEvent[] }) {
  return (
    <>
      {/* Vertical layout below sm */}
      <div className="flex flex-col gap-3 sm:hidden">
        {PIPELINE_STAGES.map((stage, index) => {
          const status = stepStatus(stage, events, jobState);
          const isLast = index === PIPELINE_STAGES.length - 1;
          const needsHumanFlag = isLast && jobState === "needs_human";
          return (
            <div key={stage} className="flex items-center gap-3">
              <div className="flex flex-col items-center">
                <StepNode status={status} index={index} />
                {!isLast && (
                  <Connector
                    vertical
                    complete={status === "complete"}
                    active={status === "active"}
                  />
                )}
              </div>
              <span className="text-sm text-[var(--text-muted)]">
                {LABELS[stage]}
                {needsHumanFlag && <span className="ml-2 text-xs text-[var(--warn)]">⚑ needs human</span>}
              </span>
            </div>
          );
        })}
      </div>

      {/* Horizontal layout at sm and up */}
      <div className="hidden items-center overflow-x-auto pb-2 sm:flex">
        {PIPELINE_STAGES.map((stage, index) => {
          const status = stepStatus(stage, events, jobState);
          const isLast = index === PIPELINE_STAGES.length - 1;
          const needsHumanFlag = isLast && jobState === "needs_human";
          return (
            <div key={stage} className="flex items-center">
              <div className="flex flex-col items-center gap-1.5">
                <StepNode status={status} index={index} />
                <span
                  className={`whitespace-nowrap text-[11px] ${
                    status === "active" ? "font-medium text-[var(--accent-bright)]" : "text-[var(--text-faint)]"
                  }`}
                >
                  {LABELS[stage]}
                </span>
                {needsHumanFlag && <span className="text-[11px] text-[var(--warn)]">⚑ needs human</span>}
              </div>
              {!isLast && (
                <Connector complete={status === "complete"} active={status === "active"} />
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
