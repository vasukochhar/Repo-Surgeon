import type { PRResult } from "@/lib/types";
import { GlowCard } from "@/components/ui/GlowCard";

export function PRPanel({ prs }: { prs: PRResult[] }) {
  if (prs.length === 0) return null;
  return (
    <GlowCard className="p-5">
      <h3 className="eyebrow mb-3">Pull requests</h3>
      <ul className="space-y-2">
        {prs.map((pr) => {
          const isMock = (() => {
            try {
              return new URL(pr.url).hostname === "example.invalid";
            } catch {
              return false;
            }
          })();
          return (
            <li key={pr.url}>
              <a
                href={pr.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex items-center justify-between gap-3 rounded-[var(--radius-md)] bg-[var(--surface-2)] px-4 py-3 text-sm transition-colors duration-[var(--dur-fast)] hover:bg-[var(--surface-2)]/70"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-xs text-[var(--accent-bright)] group-hover:text-[var(--accent)]">
                    {pr.url}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    {isMock && (
                      <span className="rounded-full bg-[var(--surface-1)] px-2 py-0.5 text-[11px] text-[var(--text-faint)]">
                        mock PR (GitHub layer pending)
                      </span>
                    )}
                    <span className="text-xs text-[var(--text-faint)]">covers {pr.item_ids.length} item(s)</span>
                  </div>
                </div>
                <span
                  aria-hidden="true"
                  className="text-[var(--text-faint)] transition-transform duration-[var(--dur-fast)] group-hover:translate-x-1 group-hover:text-[var(--accent)]"
                >
                  →
                </span>
              </a>
            </li>
          );
        })}
      </ul>
    </GlowCard>
  );
}
