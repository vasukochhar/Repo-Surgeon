import type { PRResult } from "@/lib/types";

export function PRPanel({ prs }: { prs: PRResult[] }) {
  if (prs.length === 0) return null;
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
      <h3 className="mb-3 text-sm font-medium uppercase tracking-wide text-neutral-500">Pull requests</h3>
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
            <li key={pr.url} className="flex flex-wrap items-center gap-2 text-sm">
              <a
                href={pr.url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-blue-400 hover:text-blue-300 hover:underline"
              >
                {pr.url}
              </a>
              {isMock && (
                <span className="rounded-full bg-neutral-700 px-2 py-0.5 text-[11px] text-neutral-300">
                  mock PR (GitHub layer pending)
                </span>
              )}
              <span className="text-xs text-neutral-500">covers {pr.item_ids.length} item(s)</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
