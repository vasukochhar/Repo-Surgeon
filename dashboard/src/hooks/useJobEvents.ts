"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getJob, jobEventsUrl } from "@/lib/api";
import type { JobDetail, PipelineEvent } from "@/lib/types";

function eventKey(event: PipelineEvent): string {
  const payload = event.payload ?? {};
  return [
    event.stage,
    event.type,
    event.ts,
    payload.item_id ?? "",
    payload.iteration ?? "",
  ].join("|");
}

export interface UseJobEventsResult {
  events: PipelineEvent[];
  job: JobDetail | null;
  connected: boolean;
  notFound: boolean;
}

export function useJobEvents(jobId: string): UseJobEventsResult {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [connected, setConnected] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const seenKeys = useRef<Set<string>>(new Set());
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const stoppedRef = useRef(false);

  const refreshJob = useCallback(async () => {
    try {
      const detail = await getJob(jobId);
      setJob(detail);
      setNotFound(false);
    } catch (error) {
      if (error instanceof Error && error.message.startsWith("404")) {
        setNotFound(true);
        stoppedRef.current = true;
        sourceRef.current?.close();
      }
    }
  }, [jobId]);

  useEffect(() => {
    let cancelled = false;
    seenKeys.current = new Set();
    stoppedRef.current = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting state for a new jobId, not deriving it from props
    setEvents([]);
    setJob(null);
    setNotFound(false);

    function connect() {
      if (cancelled || stoppedRef.current) return;
      const source = new EventSource(jobEventsUrl(jobId));
      sourceRef.current = source;

      source.onopen = () => setConnected(true);

      source.onmessage = (message) => {
        try {
          const parsed = JSON.parse(message.data) as PipelineEvent;
          const key = eventKey(parsed);
          if (seenKeys.current.has(key)) return;
          seenKeys.current.add(key);
          setEvents((prev) => [...prev, parsed].slice(-500));
          if (["started", "completed", "failed", "iteration"].includes(parsed.type)) {
            void refreshJob();
          }
        } catch {
          // ignore malformed frames
        }
      };

      source.onerror = () => {
        setConnected(false);
        source.close();
        if (!cancelled && !stoppedRef.current) {
          reconnectTimer.current = setTimeout(connect, 2000);
        }
      };
    }

    void refreshJob();
    connect();

    return () => {
      cancelled = true;
      sourceRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [jobId, refreshJob]);

  return { events, job, connected, notFound };
}
