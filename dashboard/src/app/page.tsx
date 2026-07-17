"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createJob, listJobs } from "@/lib/api";
import type { JobSummary } from "@/lib/types";
import { StateBadge } from "@/components/StateBadge";

export default function Home() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobsLoaded, setJobsLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const list = await listJobs();
      setJobs([...list].reverse());
    } catch {
      // transient network issue; keep showing the last known list
    } finally {
      setJobsLoaded(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch + poll on mount, setState only runs after the await
    void refresh();
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!/^https:\/\//.test(repoUrl.trim())) {
      setError("Enter a valid https:// repository URL.");
      return;
    }
    setSubmitting(true);
    try {
      const { job_id } = await createJob(repoUrl.trim());
      router.push(`/jobs/${job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create job.");
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-10 px-6 py-16">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Repo Surgeon</h1>
        <p className="text-neutral-400">
          Point it at any GitHub repo: baseline tests, researched breaking changes, sandboxed
          upgrades, verified fixes, risk-graded pull requests &mdash; unattended.
        </p>
      </header>

      <form onSubmit={handleSubmit} className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-6">
        <label htmlFor="repo-url" className="mb-2 block text-sm font-medium text-neutral-300">
          Repository URL
        </label>
        <div className="flex gap-3">
          <input
            id="repo-url"
            type="text"
            placeholder="https://github.com/org/repo"
            value={repoUrl}
            onChange={(event) => setRepoUrl(event.target.value)}
            disabled={submitting}
            className="flex-1 rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={submitting || !repoUrl.trim()}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Starting…" : "Operate"}
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      </form>

      <section className="space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">Recent jobs</h2>
        {!jobsLoaded ? (
          <div className="space-y-2">
            {[0, 1, 2].map((key) => (
              <div key={key} className="h-14 animate-pulse rounded-lg bg-neutral-900" />
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <p className="rounded-lg border border-dashed border-neutral-800 px-4 py-8 text-center text-sm text-neutral-500">
            No jobs yet &mdash; point the surgeon at a repository.
          </p>
        ) : (
          <ul className="divide-y divide-neutral-800 overflow-hidden rounded-lg border border-neutral-800">
            {jobs.map((job) => (
              <li key={job.id}>
                <Link
                  href={`/jobs/${job.id}`}
                  className="flex items-center justify-between gap-4 px-4 py-3 text-sm transition hover:bg-neutral-900"
                >
                  <div className="min-w-0">
                    <p className="truncate font-mono text-xs text-neutral-500">{job.id}</p>
                    <p className="truncate text-neutral-200">{job.repo_url}</p>
                  </div>
                  <StateBadge state={job.state} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
