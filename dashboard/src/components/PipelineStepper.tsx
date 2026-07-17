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

const DOT_STYLES: Record<StepStatus, string> = {
  pending: "bg-neutral-800 text-neutral-500 ring-1 ring-neutral-700",
  active: "bg-blue-600 text-white ring-4 ring-blue-500/30 animate-pulse",
  complete: "bg-emerald-600 text-white",
  failed: "bg-red-600 text-white",
};

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
                <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${DOT_STYLES[status]}`}>
                  {status === "complete" ? "✓" : index + 1}
                </div>
                {!isLast && <div className={`h-4 w-0.5 ${status === "complete" ? "bg-emerald-600" : "bg-neutral-800"}`} />}
              </div>
              <span className="text-sm text-neutral-300">
                {LABELS[stage]}
                {needsHumanFlag && <span className="ml-2 text-xs text-amber-400">⚑ needs human</span>}
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
              <div className="flex flex-col items-center gap-1">
                <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${DOT_STYLES[status]}`}>
                  {status === "complete" ? "✓" : index + 1}
                </div>
                <span className="whitespace-nowrap text-[11px] text-neutral-400">{LABELS[stage]}</span>
                {needsHumanFlag && <span className="text-[11px] text-amber-400">⚑ needs human</span>}
              </div>
              {!isLast && <div className={`mx-1 h-0.5 w-8 shrink-0 sm:w-12 ${status === "complete" ? "bg-emerald-600" : "bg-neutral-800"}`} />}
            </div>
          );
        })}
      </div>
    </>
  );
}
