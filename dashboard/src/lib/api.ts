import type { JobDetail, JobSummary } from "./types";

const BASE = "/api/backend";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  return response.json() as Promise<T>;
}

export function createJob(repoUrl: string): Promise<{ job_id: string }> {
  return request("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_url: repoUrl }),
  });
}

export function listJobs(): Promise<JobSummary[]> {
  return request("/jobs");
}

export function getJob(jobId: string): Promise<JobDetail> {
  return request(`/jobs/${jobId}`);
}

export function jobEventsUrl(jobId: string): string {
  return `${BASE}/jobs/${jobId}/events`;
}

export function jobLogsStreamUrl(jobId: string): string {
  return `${BASE}/jobs/${jobId}/logs/stream`;
}

export function listTraceFiles(jobId: string): Promise<{ files: string[] }> {
  return request(`/jobs/${jobId}/trace`);
}

export function getTraceFile(jobId: string, filename: string): Promise<unknown> {
  return request(`/jobs/${jobId}/trace/${encodeURIComponent(filename)}`);
}
