import type { IterationPayload, SurgeonResult, UpgradeItem } from "@/lib/types";
import { DiffViewer } from "./DiffViewer";
import { grade, GRADE_STYLES } from "@/lib/quality";

const MAX_ITERATIONS = 5;

function AttemptDots({ iterations }: { iterations: IterationPayload[] }) {
  const byIteration = new Map(iterations.map((it) => [it.iteration, it.passed]));
  return (
    <div className="flex gap-1">
      {Array.from({ length: MAX_ITERATIONS }, (_, index) => index + 1).map((n) => {
        const passed = byIteration.get(n);
        const color = passed === true ? "bg-emerald-500" : passed === false ? "bg-red-500" : "bg-neutral-800";
        return <span key={n} className={`h-2.5 w-2.5 rounded-full ${color}`} title={`Attempt ${n}`} />;
      })}
    </div>
  );
}

function ScoreStat({ label, value, isPercent }: { label: string; value: number | null; isPercent?: boolean }) {
  const gradeWord = grade(value);
  return (
    <div className="rounded-lg bg-neutral-950 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</p>
      {value == null ? (
        <p className="text-sm text-neutral-600">— available in real mode</p>
      ) : (
        <p className={`text-lg font-semibold ${GRADE_STYLES[gradeWord ?? ""] ?? "text-neutral-200"}`}>
          {value}
          {isPercent ? "%" : ""}
          {gradeWord && <span className="ml-2 text-xs font-normal capitalize">{gradeWord}</span>}
        </p>
      )}
    </div>
  );
}

export function ItemCard({
  item,
  iterations,
  result,
}: {
  item: UpgradeItem;
  iterations: IterationPayload[];
  result: SurgeonResult | undefined;
}) {
  const latest = iterations[iterations.length - 1];
  const statusLabel = result
    ? result.status === "green"
      ? `✓ Green in ${result.iterations} iteration${result.iterations === 1 ? "" : "s"}`
      : result.status === "needs_human"
        ? `⚑ Needs human after ${result.iterations} attempts`
        : "Failed"
    : "In progress…";
  const statusColor = result
    ? result.status === "green"
      ? "text-emerald-400"
      : result.status === "needs_human"
        ? "text-amber-400"
        : "text-red-400"
    : "text-blue-400";

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-sm text-neutral-200">{item.dependency}</p>
          <p className="font-mono text-xs text-neutral-500">
            {item.from_version} → {item.to_version}
          </p>
        </div>
        <p className={`text-sm font-medium ${statusColor}`}>{statusLabel}</p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-4">
        <AttemptDots iterations={iterations} />
        {latest && (
          <span className="text-xs text-neutral-500">
            {latest.tests_passed ?? 0} passed / {latest.tests_failed ?? 0} failed
          </span>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <ScoreStat label="Injected-bug catch rate" value={latest?.mutation_score ?? null} isPercent />
        <ScoreStat label="Test quality score" value={latest?.test_quality_score ?? null} />
      </div>

      {result && <DiffViewer patch={result.patch} filesChanged={result.files_changed} />}
    </div>
  );
}
