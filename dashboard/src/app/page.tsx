"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createJob, listJobs } from "@/lib/api";
import type { JobSummary } from "@/lib/types";
import { StateBadge } from "@/components/StateBadge";
import { GlowCard } from "@/components/ui/GlowCard";
import { MagneticField } from "@/components/fx/MagneticField";
import { staggerDelay } from "@/lib/motion";

const EXAMPLE_REPOS = [
  "https://github.com/org/legacy-service",
  "https://github.com/acme/payments-api",
  "https://github.com/your-org/your-repo",
];

function useTypewriterPlaceholder(active: boolean): string {
  const [text, setText] = useState("");
  useEffect(() => {
    if (!active) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot sync with a media query unavailable during SSR
      setText(EXAMPLE_REPOS[0]);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function loop() {
      let repoIndex = 0;
      while (!cancelled) {
        const full = EXAMPLE_REPOS[repoIndex % EXAMPLE_REPOS.length];
        for (let i = 0; i <= full.length && !cancelled; i++) {
          setText(full.slice(0, i));
          await new Promise((resolve) => {
            timer = setTimeout(resolve, 28);
          });
        }
        await new Promise((resolve) => {
          timer = setTimeout(resolve, 1400);
        });
        for (let i = full.length; i >= 0 && !cancelled; i--) {
          setText(full.slice(0, i));
          await new Promise((resolve) => {
            timer = setTimeout(resolve, 14);
          });
        }
        await new Promise((resolve) => {
          timer = setTimeout(resolve, 300);
        });
        repoIndex++;
      }
    }
    void loop();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active]);
  return text;
}

export default function Home() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = useState("");
  const [focused, setFocused] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobsLoaded, setJobsLoaded] = useState(false);
  const errorFlashRef = useRef<HTMLDivElement>(null);

  const placeholder = useTypewriterPlaceholder(!focused && !repoUrl && !submitting);

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
    <main className="flex w-full flex-1 flex-col">
      <section className="relative isolate overflow-hidden border-b border-[var(--border)]">
        <MagneticField className="absolute inset-0 -z-10" />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            background:
              "radial-gradient(60% 50% at 50% 40%, transparent 0%, var(--bg) 100%)",
          }}
        />
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 py-20 sm:py-28">
          <div className="rise-in space-y-4 text-center">
            <span className="eyebrow">Autonomous codebase surgery</span>
            <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
              Operates on your repo.
              <br />
              <span className="text-[var(--accent)]">Unattended.</span>
            </h1>
            <p className="mx-auto max-w-xl text-[var(--text-muted)]">
              Baseline tests, researched breaking changes, sandboxed upgrades, verified
              fixes, risk-graded pull requests &mdash; point it at a repo and step back.
            </p>
          </div>

          <form
            onSubmit={handleSubmit}
            className="rise-in"
            style={{ animationDelay: "120ms" }}
          >
            <div
              className="flex flex-col gap-3 rounded-[var(--radius-lg)] border p-2 transition-[border-color,box-shadow] duration-[var(--dur-base)] sm:flex-row"
              style={{
                borderColor: focused ? "var(--accent)" : "var(--border)",
                boxShadow: focused ? "var(--glow-accent)" : "none",
                background: "var(--surface-1)",
              }}
            >
              <input
                id="repo-url"
                type="text"
                aria-label="Repository URL"
                placeholder={placeholder || "https://github.com/org/repo"}
                value={repoUrl}
                onChange={(event) => setRepoUrl(event.target.value)}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                disabled={submitting}
                className="h-14 flex-1 rounded-[var(--radius-md)] bg-transparent px-4 font-mono text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-faint)] disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={submitting || !repoUrl.trim()}
                className="h-14 shrink-0 rounded-[var(--radius-md)] bg-[var(--accent)] px-6 text-sm font-semibold text-[#04110d] transition-[transform,filter] duration-[var(--dur-fast)] hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40 disabled:active:scale-100"
              >
                {submitting ? "Starting…" : "Operate"}
              </button>
            </div>
            {error && (
              <div ref={errorFlashRef} className="rise-in mt-3 text-sm text-[var(--danger)]">
                {error}
              </div>
            )}
          </form>
        </div>
      </section>

      <section className="mx-auto w-full max-w-3xl flex-1 space-y-3 px-6 py-12">
        <h2 className="eyebrow">Recent operations</h2>
        {!jobsLoaded ? (
          <div className="space-y-2">
            {[0, 1, 2].map((key) => (
              <div
                key={key}
                className="h-16 animate-pulse rounded-[var(--radius-lg)]"
                style={{ background: "var(--surface-1)" }}
              />
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <div className="rounded-[var(--radius-lg)] border border-dashed border-[var(--border)] px-4 py-12 text-center text-sm text-[var(--text-faint)]">
            No operations yet &mdash; point the surgeon at a repository.
          </div>
        ) : (
          <ul className="space-y-2">
            {jobs.map((job, index) => (
              <li
                key={job.id}
                className="rise-in"
                style={{ animationDelay: staggerDelay(index) }}
              >
                <GlowCard>
                  <Link
                    href={`/jobs/${job.id}`}
                    className="flex items-center justify-between gap-4 px-5 py-4"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-[var(--text)]">
                        {job.repo_url}
                      </p>
                      <p className="truncate font-mono text-xs text-[var(--text-faint)]">
                        {job.id}
                      </p>
                    </div>
                    <StateBadge state={job.state} />
                  </Link>
                </GlowCard>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
