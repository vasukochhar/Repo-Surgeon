import type { RepoProfile } from "@/lib/types";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-600/20 text-red-300",
  high: "bg-orange-600/20 text-orange-300",
  moderate: "bg-amber-600/20 text-amber-300",
  medium: "bg-amber-600/20 text-amber-300",
  low: "bg-neutral-700 text-neutral-300",
};

export function ScoutSummary({ profile }: { profile: RepoProfile }) {
  const { baseline, security_report: security } = profile;
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
      <h3 className="mb-3 text-sm font-medium uppercase tracking-wide text-neutral-500">Scout report</h3>
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded-full bg-neutral-800 px-2.5 py-1">{profile.language}</span>
        <span className="rounded-full bg-neutral-800 px-2.5 py-1">{profile.package_manager}</span>
        <span className="rounded-full bg-neutral-800 px-2.5 py-1">{profile.test_runner}</span>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-neutral-500">Tests</dt>
          <dd className="font-medium text-neutral-200">
            {baseline.tests_passed} passed
            {baseline.tests_failed > 0 && <span className="text-red-400"> / {baseline.tests_failed} failed</span>}
          </dd>
        </div>
        <div>
          <dt className="text-neutral-500">Build</dt>
          <dd className={`font-medium ${baseline.build_ok ? "text-emerald-400" : "text-red-400"}`}>
            {baseline.build_ok ? "OK" : "Failing"}
          </dd>
        </div>
        <div>
          <dt className="text-neutral-500">Coverage</dt>
          <dd className="font-medium text-neutral-200">{baseline.coverage != null ? `${baseline.coverage}%` : "—"}</dd>
        </div>
        <div>
          <dt className="text-neutral-500">Dependencies</dt>
          <dd className="font-medium text-neutral-200">{profile.dependencies.length}</dd>
        </div>
      </dl>
      {security.total > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs text-neutral-500">
            {security.total} known {security.total === 1 ? "vulnerability" : "vulnerabilities"}
          </p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(security.counts_by_severity).map(([severity, count]) => (
              <span
                key={severity}
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${SEVERITY_STYLES[severity.toLowerCase()] ?? "bg-neutral-700 text-neutral-300"}`}
              >
                {severity}: {count}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
