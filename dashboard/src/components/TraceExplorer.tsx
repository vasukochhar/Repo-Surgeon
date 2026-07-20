"use client";

import { useEffect, useState } from "react";
import { getTraceFile, listTraceFiles } from "@/lib/api";
import type { JobState } from "@/lib/types";

function splitName(filename: string): { step: string; label: string } {
  const match = filename.match(/^(\d+)_(.+)\.json$/);
  return match ? { step: match[1], label: match[2] } : { step: "", label: filename };
}

const TERMINAL: JobState[] = ["done", "needs_human", "failed"];

export function TraceExplorer({ jobId, jobState }: { jobId: string; jobState: JobState }) {
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    async function poll() {
      try {
        const result = await listTraceFiles(jobId);
        if (!cancelled) setFiles(result.files);
      } catch {
        // trace dir not created yet, or tracing disabled — keep the panel quiet
      }
    }
    void poll();
    const interval = TERMINAL.includes(jobState) ? null : setInterval(poll, 2000);
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [open, jobId, jobState]);

  async function openFile(filename: string) {
    setSelected(filename);
    setLoading(true);
    try {
      const data = await getTraceFile(jobId, filename);
      setContent(JSON.stringify(data, null, 2));
    } catch (error) {
      setContent(`Failed to load: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface-1)]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between px-5 py-3 text-sm font-medium text-[var(--text-muted)]"
      >
        <span className="eyebrow">Data flow — test_results/ ({files.length})</span>
        <span className="text-[var(--text-faint)]">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="grid grid-cols-1 gap-0 border-t border-[var(--border)] sm:grid-cols-[220px_1fr]">
          <div className="max-h-96 overflow-y-auto border-b border-[var(--border)] p-2 sm:border-b-0 sm:border-r">
            {files.length === 0 ? (
              <p className="px-2 py-3 text-xs text-[var(--text-faint)]">
                No trace files yet — they appear as each stage finishes. If this stays empty, tracing may be off
                (REPO_SURGEON_TRACE=0).
              </p>
            ) : (
              files.map((filename) => {
                const { step, label } = splitName(filename);
                const active = filename === selected;
                return (
                  <button
                    key={filename}
                    type="button"
                    onClick={() => void openFile(filename)}
                    className={`flex w-full items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-left font-mono text-[11px] ${
                      active
                        ? "bg-[var(--accent-dim)] text-[var(--accent-bright)]"
                        : "text-[var(--text-muted)] hover:bg-[var(--surface-2)]"
                    }`}
                  >
                    <span className="text-[var(--text-faint)]">{step}</span>
                    <span className="truncate">{label}</span>
                  </button>
                );
              })
            )}
          </div>
          <div className="max-h-96 overflow-auto bg-[var(--bg)] p-3">
            {!selected ? (
              <p className="text-xs text-[var(--text-faint)]">Select a file to view its exact input/output JSON.</p>
            ) : loading ? (
              <p className="text-xs text-[var(--text-faint)]">Loading…</p>
            ) : (
              <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-[var(--text)]">
                {content}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
