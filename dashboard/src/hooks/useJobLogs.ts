"use client";

import { useEffect, useRef, useState } from "react";
import { jobLogsStreamUrl } from "@/lib/api";

export interface LogEntry {
  seq: number;
  ts: number;
  level: string;
  logger: string;
  message: string;
}

const MAX_LINES = 2000;

export function useJobLogs(jobId: string): { logs: LogEntry[]; connected: boolean } {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting for a new jobId
    setLogs([]);

    function connect() {
      if (cancelled) return;
      const source = new EventSource(jobLogsStreamUrl(jobId));
      sourceRef.current = source;
      source.onopen = () => setConnected(true);
      source.onmessage = (message) => {
        try {
          const entry = JSON.parse(message.data) as LogEntry;
          setLogs((prev) => [...prev, entry].slice(-MAX_LINES));
        } catch {
          // ignore malformed frames
        }
      };
      source.onerror = () => {
        setConnected(false);
        source.close();
        if (!cancelled) reconnectTimer.current = setTimeout(connect, 2000);
      };
    }

    connect();
    return () => {
      cancelled = true;
      sourceRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [jobId]);

  return { logs, connected };
}
