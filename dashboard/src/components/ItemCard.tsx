import type { IterationPayload, SurgeonResult, UpgradeItem } from "@/lib/types";
import { DiffViewer } from "./DiffViewer";
import { grade, GRADE_STYLES } from "@/lib/quality";
import { GlowCard } from "@/components/ui/GlowCard";
import { AnimatedNumber } from "@/components/ui/AnimatedNumber";

const MAX_ITERATIONS = 5;

function AttemptDots({ iterations }: { iterations: IterationPayload[] }) {
  const byIteration = new Map(iterations.map((it) => [it.iteration, it.passed]));
  const latestAttempt = iterations.length;
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: MAX_ITERATIONS }, (_, index) => index + 1).map((n) => {
        const passed = byIteration.get(n);
        const isRunning = passed === undefined && n === latestAttempt + 1 && latestAttempt > 0 && !byIteration.get(latestAttempt);
        const className =
          passed === true
            ? "bg-[var(--ok)] scale-100"
            : passed === false
              ? "bg-[var(--danger)] scale-100"
              : isRunning
                ? "dot-live"
                : "bg-transparent ring-1 ring-inset ring-[var(--border-strong)]";
        return (
          <span
            key={n}
            className={`h-3 w-3 rounded-full transition-transform duration-[var(--dur-base)] ease-[var(--ease-spring)] ${className}`}
            title={`Attempt ${n}`}
          />
        );
      })}
    </div>
  );
}

function ScoreStat({ label, value, isPercent }: { label: string; value: number | null; isPercent?: boolean }) {
  const gradeWord = grade(value);
  return (
    <div className="rounded-[var(--radius-md)] bg-[var(--surface-2)] px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-[var(--text-faint)]">{label}</p>
      {value == null ? (
        <p className="text-sm text-[var(--text-faint)]">— available in real mode</p>
      ) : (
        <p className={`text-lg font-semibold ${GRADE_STYLES[gradeWord ?? ""] ?? "text-[var(--text)]"}`}>
          <AnimatedNumber value={value} suffix={isPercent ? "%" : ""} />
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
      ? "text-[var(--ok)]"
      : result.status === "needs_human"
        ? "text-[var(--warn)]"
        : "text-[var(--danger)]"
    : "text-[var(--accent-bright)]";
  const borderTint = result
    ? result.status === "green"
      ? "var(--ok)"
      : result.status === "needs_human"
        ? "var(--warn)"
        : "var(--danger)"
    : "var(--accent)";

  return (
    <GlowCard className="p-5" style={{ borderColor: `color-mix(in srgb, ${borderTint} 25%, var(--border))` }}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-sm text-[var(--text)]">{item.dependency}</p>
          <p className="font-mono text-xs text-[var(--text-faint)]">
            {item.from_version} → {item.to_version}
          </p>
        </div>
        <p className={`text-sm font-medium ${statusColor}`}>{statusLabel}</p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-4">
        <AttemptDots iterations={iterations} />
        {latest && (
          <span className="text-xs text-[var(--text-faint)]">
            {latest.tests_passed ?? 0} passed / {latest.tests_failed ?? 0} failed
          </span>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <ScoreStat label="Injected-bug catch rate" value={latest?.mutation_score ?? null} isPercent />
        <ScoreStat label="Test quality score" value={latest?.test_quality_score ?? null} />
      </div>

      {result && <DiffViewer patch={result.patch} filesChanged={result.files_changed} />}
    </GlowCard>
  );
}
