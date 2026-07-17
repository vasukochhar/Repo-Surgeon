import type { RepoProfile } from "@/lib/types";
import { AnimatedNumber } from "@/components/ui/AnimatedNumber";
import { GlowCard } from "@/components/ui/GlowCard";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-[var(--danger)]/15 text-[var(--danger)]",
  high: "bg-orange-500/15 text-orange-300",
  moderate: "bg-[var(--warn)]/15 text-[var(--warn)]",
  medium: "bg-[var(--warn)]/15 text-[var(--warn)]",
  low: "bg-[var(--surface-2)] text-[var(--text-muted)]",
};

export function ScoutSummary({ profile }: { profile: RepoProfile }) {
  const { baseline, security_report: security } = profile;
  return (
    <GlowCard className="p-5">
      <h3 className="eyebrow mb-3">Scout report</h3>
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-[var(--text-muted)]">{profile.language}</span>
        <span className="rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-[var(--text-muted)]">{profile.package_manager}</span>
        <span className="rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-[var(--text-muted)]">{profile.test_runner}</span>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-[var(--text-faint)]">Tests</dt>
          <dd className="font-medium text-[var(--text)]">
            <AnimatedNumber value={baseline.tests_passed} /> passed
            {baseline.tests_failed > 0 && (
              <span className="text-[var(--danger)]">
                {" "}
                / <AnimatedNumber value={baseline.tests_failed} /> failed
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--text-faint)]">Build</dt>
          <dd className={`font-medium ${baseline.build_ok ? "text-[var(--ok)]" : "text-[var(--danger)]"}`}>
            {baseline.build_ok ? "✓ OK" : "✕ Failing"}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--text-faint)]">Coverage</dt>
          <dd className="font-medium text-[var(--text)]">
            {baseline.coverage != null ? (
              <>
                <AnimatedNumber value={baseline.coverage} suffix="%" />
              </>
            ) : (
              "—"
            )}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--text-faint)]">Dependencies</dt>
          <dd className="font-medium text-[var(--text)]">
            <AnimatedNumber value={profile.dependencies.length} />
          </dd>
        </div>
      </dl>
      {security.total > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs text-[var(--text-faint)]">
            {security.total} known {security.total === 1 ? "vulnerability" : "vulnerabilities"}
          </p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(security.counts_by_severity).map(([severity, count]) => (
              <span
                key={severity}
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${SEVERITY_STYLES[severity.toLowerCase()] ?? "bg-[var(--surface-2)] text-[var(--text-muted)]"}`}
              >
                {severity}: {count}
              </span>
            ))}
          </div>
        </div>
      )}
    </GlowCard>
  );
}
