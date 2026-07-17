"use client";

import { useState } from "react";

function lineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "text-[var(--text-faint)]";
  if (line.startsWith("@@")) return "bg-[var(--info)]/10 text-[var(--info)]";
  if (line.startsWith("diff --git") || line.startsWith("index ")) return "text-[var(--text-faint)]";
  if (line.startsWith("+")) return "bg-[var(--ok)]/10 text-[var(--ok)]";
  if (line.startsWith("-")) return "bg-[var(--danger)]/10 text-[var(--danger)]";
  return "text-[var(--text-muted)]";
}

export function DiffViewer({ patch, filesChanged }: { patch: string; filesChanged: string[] }) {
  const [open, setOpen] = useState(false);
  const lines = patch.trim().split("\n");

  return (
    <div className="mt-3">
      {filesChanged.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {filesChanged.map((file) => (
            <span key={file} className="rounded bg-[var(--surface-2)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-muted)]">
              {file}
            </span>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="text-xs font-medium text-[var(--accent-bright)] hover:text-[var(--accent)]"
      >
        {open ? "Hide patch" : "View patch"}
      </button>
      <div
        className="grid overflow-hidden transition-[grid-template-rows] duration-[var(--dur-slow)] ease-[var(--ease-out)]"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      >
        <div className="min-h-0">
          <div className="mt-2 max-h-80 overflow-auto rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg)]">
            {!patch.trim() ? (
              <p className="p-3 text-xs text-[var(--text-faint)]">No patch captured — mock mode.</p>
            ) : (
              <pre className="min-w-max p-3 font-mono text-[11px] leading-5">
                {lines.map((line, index) => (
                  <div key={index} className={lineClass(line)}>
                    {line || " "}
                  </div>
                ))}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
