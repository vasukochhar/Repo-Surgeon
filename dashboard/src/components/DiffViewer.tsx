"use client";

import { useState } from "react";

function lineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "text-neutral-500";
  if (line.startsWith("@@")) return "bg-blue-950/40 text-blue-300";
  if (line.startsWith("diff --git") || line.startsWith("index ")) return "text-neutral-500";
  if (line.startsWith("+")) return "bg-emerald-950/40 text-emerald-300";
  if (line.startsWith("-")) return "bg-red-950/40 text-red-300";
  return "text-neutral-400";
}

export function DiffViewer({ patch, filesChanged }: { patch: string; filesChanged: string[] }) {
  const [open, setOpen] = useState(false);
  const lines = patch.trim().split("\n");

  return (
    <div className="mt-3">
      {filesChanged.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {filesChanged.map((file) => (
            <span key={file} className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[11px] text-neutral-400">
              {file}
            </span>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="text-xs font-medium text-blue-400 hover:text-blue-300"
      >
        {open ? "Hide patch" : "View patch"}
      </button>
      {open && (
        <div className="mt-2 max-h-80 overflow-auto rounded-lg border border-neutral-800 bg-neutral-950">
          {!patch.trim() ? (
            <p className="p-3 text-xs text-neutral-500">No patch captured — mock mode.</p>
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
      )}
    </div>
  );
}
