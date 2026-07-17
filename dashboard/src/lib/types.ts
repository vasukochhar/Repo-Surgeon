export type JobState =
  | "queued"
  | "scouting"
  | "researching"
  | "planning"
  | "operating"
  | "reviewing"
  | "watching_ci"
  | "done"
  | "needs_human"
  | "failed";

export const PIPELINE_STAGES: JobState[] = [
  "scouting",
  "researching",
  "planning",
  "operating",
  "reviewing",
  "watching_ci",
  "done",
];

export const TERMINAL_STATES: JobState[] = ["done", "needs_human", "failed"];

export interface PipelineEvent {
  job_id: string;
  stage: string;
  type: "started" | "completed" | "iteration" | "failed" | string;
  ts: string;
  payload: Record<string, unknown>;
}

export interface IterationPayload {
  item_id: string;
  iteration: number;
  passed: boolean;
  tests_passed?: number;
  tests_failed?: number;
  newly_failing_tests?: string[];
  test_quality_score?: number | null;
  mutation_score?: number | null;
}

export type UpgradeCategory = "security" | "patch" | "minor" | "major";

export interface UpgradeItem {
  id: string;
  dependency: string;
  from_version: string;
  to_version: string;
  category: UpgradeCategory;
  risk: number;
  rationale: string;
  breaking_change_ref?: string | null;
}

export interface UpgradePlan {
  items: UpgradeItem[];
}

export interface Baseline {
  tests_passed: number;
  tests_failed: number;
  build_ok: boolean;
  coverage: number | null;
  tests_skipped: number;
  failing_tests: string[];
}

export interface Dependency {
  name: string;
  version: string;
  latest_version?: string | null;
  direct?: boolean | null;
  ecosystem?: string | null;
}

export interface SecurityReport {
  total: number;
  counts_by_severity: Record<string, number>;
  fix_available_count: number;
  findings: Array<{
    dependency: string;
    severity: string;
    identifier?: string | null;
    summary?: string | null;
  }>;
}

export interface StackInfo {
  language: string;
  package_manager: string;
  test_runner: string;
  build_tool?: string | null;
  is_monorepo: boolean;
}

export interface RepoProfile {
  language: string;
  package_manager: string;
  test_runner: string;
  baseline: Baseline;
  dependencies: Dependency[];
  security_report: SecurityReport;
  stack?: StackInfo | null;
}

export type SurgeonStatus = "green" | "needs_human" | "failed";

export interface SurgeonResult {
  item_id: string;
  status: SurgeonStatus;
  iterations: number;
  files_changed: string[];
  patch: string;
}

export interface PRResult {
  url: string;
  item_ids: string[];
}

export interface JobSummary {
  id: string;
  repo_url: string;
  state: JobState;
  error: string | null;
}

export interface JobDetail extends JobSummary {
  results: SurgeonResult[];
  prs: PRResult[];
  profile: RepoProfile | null;
  plan: UpgradePlan | null;
}
