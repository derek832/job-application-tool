/**
 * Typed Automator API client.
 *
 * Single module for all communication between the Web App and the
 * locally-hosted Automator service (proxied through nginx). Zod schemas mirror
 * the Pydantic response models defined in automator/src/api/schemas.py.
 */

import { z } from "zod";
import {
  NtfyConfigResponse,
  NtfyConfigResponseSchema,
  NtfyConfigUpdate,
} from "../types/ntfy";

export type { NtfyConfigResponse, NtfyConfigUpdate };
export { NtfyConfigResponseSchema };

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = "/api";

// ---------------------------------------------------------------------------
// Custom Error
// ---------------------------------------------------------------------------

/**
 * Typed error class for API failures. Components should catch this rather than
 * dealing with raw fetch errors or unknown response shapes.
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly detail: string
  ) {
    super(`API ${status} ${statusText}: ${detail}`);
    this.name = "ApiError";
  }
}

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

export const StatsOutSchema = z.object({
  total_discovered: z.number().int(),
  total_applied: z.number().int(),
  total_skipped: z.number().int(),
  total_pending_review: z.number().int(),
  application_success_rate: z.number(),
});

export const HealthResponseSchema = z.object({
  claude_api: z.boolean(),
  gmail: z.boolean(),
  google_docs: z.boolean(),
});

export const StatusResponseSchema = z.object({
  status: z.enum(["running", "paused", "idle", "error"]),
  last_run_at: z.string().nullable(),
  next_run_at: z.string().nullable(),
  queue_count: z.number().int(),
  stats: StatsOutSchema,
  health: HealthResponseSchema,
});

export const JobRecordOutSchema = z.object({
  id: z.string(),
  job_title: z.string(),
  company: z.string(),
  location: z.string().nullable(),
  linkedin_url: z.string(),
  external_url: z.string().nullable(),
  apply_type: z.string(),
  status: z.string(),
  fit_score: z.number().int().nullable(),
  fit_rationale: z.string().nullable(),
  description_text: z.string().nullable(),
  resume_snapshot: z.string().nullable(),
  tailored_resume_text: z.string().nullable(),
  tailored_resume_pdf: z.string().nullable(),
  cover_letter_text: z.string().nullable(),
  error_message: z.string().nullable(),
  queue_reason: z.string().nullable(),
  application_notes: z.string().nullable(),
  run_id: z.string().nullable(),
  claude_cost_usd: z.number().nullable(),
  discovered_at: z.string(),
  extracted_at: z.string().nullable(),
  scored_at: z.string().nullable(),
  approved_at: z.string().nullable(),
  applied_at: z.string().nullable(),
  updated_at: z.string(),
});

export const QueueItemOutSchema = z.object({
  job_id: z.string(),
  job_title: z.string(),
  company: z.string(),
  linkedin_url: z.string(),
  queue_reason: z.string().nullable(),
  fit_score: z.number().int().nullable(),
  fit_rationale: z.string().nullable(),
  status: z.string(),
  tailored_resume_pdf: z.string().nullable(),
  added_at: z.string(),
});

export const SearchConfigSchema = z.object({
  keywords: z.string().nullable(),
  search_queries: z.array(z.string()),
  location: z.string().nullable(),
  job_type: z.string().nullable(),
  experience_level: z.string().nullable(),
  remote_pref: z.string().nullable(),
});

export const GoalsProfileSchema = z.object({
  target_titles: z.array(z.string()),
  industries: z.array(z.string()),
  company_sizes: z.array(z.string()),
  geo_prefs: z.array(z.string()),
  min_salary: z.number().int().nullable(),
  deal_breakers: z.array(z.string()),
  open_to_stretch: z.boolean(),
  career_objective: z.string().nullable(),
  supplementary_context: z.string().nullable(),
});

export const UserProfileSchema = z.object({
  full_name: z.string().nullable(),
  email: z.string().nullable(),
  phone: z.string().nullable(),
  location: z.string().nullable(),
  work_auth: z.string().nullable(),
  linkedin_url: z.string().nullable(),
  common_answers: z.record(z.string(), z.string()),
});

export const SettingsSchema = z.object({
  claude_api_key: z.string().nullable(),
  gmail_user: z.string().nullable(),
  sms_gateway: z.string().nullable(),
  gdocs_script_url: z.string().nullable(),
  good_fit_threshold: z.number().int(),
  stretch_threshold: z.number().int(),
  external_apply_threshold: z.number().int(),
  human_review_threshold: z.number().int(),
  skip_viewed_jobs: z.boolean(),
  backup_dir: z.string().nullable(),
  dry_run: z.boolean(),
});

export const LanDetectResponseSchema = z.object({
  lan_base_url: z.string(),
  port: z.number().int(),
});

export const ScheduleConfigResponseSchema = z.object({
  mode: z.enum(["specific_times", "interval"]).default("specific_times"),
  times: z.array(z.string()).default([]),
  interval_hours: z.number().int().default(2),
  window_start: z.string().default("08:00"),
  window_end: z.string().default("20:00"),
  weekend_runs: z.boolean().default(false),
  timezone: z.string().default("America/New_York"),
  quiet_hours_start: z.string().nullable().default(null),
  quiet_hours_end: z.string().nullable().default(null),
});

export const ScheduleNextResponseSchema = z.object({
  next_runs: z.array(z.string()),
});

// ---------------------------------------------------------------------------
// Chrome & Session Health Schemas
// ---------------------------------------------------------------------------

export const ChromeStatusResponseSchema = z.object({
  connected: z.boolean(),
  browser_version: z.string().nullable().optional(),
  debugger_url: z.string().nullable().optional(),
});

export const SessionHealthResponseSchema = z.object({
  chrome_reachable: z.boolean(),
  linkedin_authenticated: z.boolean(),
  error_message: z.string().nullable(),
  checked_at: z.string(),
});

export const ChromeLaunchResponseSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  already_running: z.boolean().optional(),
});

// ---------------------------------------------------------------------------
// Inferred TypeScript Types
// ---------------------------------------------------------------------------

export type StatsOut = z.infer<typeof StatsOutSchema>;
export type HealthResponse = z.infer<typeof HealthResponseSchema>;
export type StatusResponse = z.infer<typeof StatusResponseSchema>;
export type JobRecordOut = z.infer<typeof JobRecordOutSchema>;
export type QueueItemOut = z.infer<typeof QueueItemOutSchema>;
export type SearchConfig = z.infer<typeof SearchConfigSchema>;
export type GoalsProfile = z.infer<typeof GoalsProfileSchema>;
export type UserProfile = z.infer<typeof UserProfileSchema>;
export type Settings = z.infer<typeof SettingsSchema>;
export type LanDetectResponse = z.infer<typeof LanDetectResponseSchema>;
export type ScheduleConfigResponse = z.infer<typeof ScheduleConfigResponseSchema>;
export type ScheduleNextResponse = z.infer<typeof ScheduleNextResponseSchema>;

export interface ScheduleConfigUpdate {
  mode: "specific_times" | "interval";
  times: string[];
  interval_hours: number;
  window_start: string;
  window_end: string;
  weekend_runs: boolean;
  timezone: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
}
export type ChromeStatusResponse = z.infer<typeof ChromeStatusResponseSchema>;
export type SessionHealthResponse = z.infer<typeof SessionHealthResponseSchema>;
export type ChromeLaunchResponse = z.infer<typeof ChromeLaunchResponseSchema>;

// ---------------------------------------------------------------------------
// Internal Helpers
// ---------------------------------------------------------------------------

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  options: RequestInit = {}
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) ?? {}),
  };

  let response: Response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch {
    throw new ApiError(0, "NetworkError", "Unable to reach the Automator service.");
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Use statusText as fallback
    }
    throw new ApiError(response.status, response.statusText, detail);
  }

  const json: unknown = await response.json();
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    throw new ApiError(
      response.status,
      "ValidationError",
      `Response validation failed: ${parsed.error.message}`
    );
  }
  return parsed.data;
}

async function requestVoid(path: string, options: RequestInit = {}): Promise<void> {
  const url = `${BASE_URL}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) ?? {}),
  };

  let response: Response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch {
    throw new ApiError(0, "NetworkError", "Unable to reach the Automator service.");
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Use statusText as fallback
    }
    throw new ApiError(response.status, response.statusText, detail);
  }
}

// ---------------------------------------------------------------------------
// System Control
// ---------------------------------------------------------------------------

export async function getStatus(): Promise<StatusResponse> {
  return request("/status", StatusResponseSchema);
}

export async function triggerRun(): Promise<void> {
  return requestVoid("/run", { method: "POST" });
}

export async function pause(): Promise<void> {
  return requestVoid("/pause", { method: "POST" });
}

export async function resume(): Promise<void> {
  return requestVoid("/resume", { method: "POST" });
}

export async function getHealth(): Promise<HealthResponse> {
  return request("/health", HealthResponseSchema);
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export async function getSearchConfig(): Promise<SearchConfig> {
  const data = await request("/config/search", SearchConfigSchema.extend({
    search_queries: z.array(z.string()).optional(),
  }));
  return { ...data, search_queries: data.search_queries ?? [] };
}

export async function updateSearchConfig(data: SearchConfig): Promise<SearchConfig> {
  const result = await request("/config/search", SearchConfigSchema.extend({
    search_queries: z.array(z.string()).optional(),
  }), {
    method: "PUT",
    body: JSON.stringify(data),
  });
  return { ...result, search_queries: result.search_queries ?? [] };
}

export async function getGoalsProfile(): Promise<GoalsProfile> {
  const data = await request("/config/goals", GoalsProfileSchema.extend({
    supplementary_context: z.string().nullable().optional(),
  }));
  return { ...data, supplementary_context: data.supplementary_context ?? null };
}

export async function updateGoalsProfile(data: GoalsProfile): Promise<GoalsProfile> {
  const result = await request("/config/goals", GoalsProfileSchema.extend({
    supplementary_context: z.string().nullable().optional(),
  }), {
    method: "PUT",
    body: JSON.stringify(data),
  });
  return { ...result, supplementary_context: result.supplementary_context ?? null };
}

export async function getUserProfile(): Promise<UserProfile> {
  return request("/config/profile", UserProfileSchema);
}

export async function updateUserProfile(data: UserProfile): Promise<UserProfile> {
  return request("/config/profile", UserProfileSchema, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

const SettingsSchemaLenient = SettingsSchema.extend({
  external_apply_threshold: z.number().int().optional(),
  human_review_threshold: z.number().int().optional(),
  skip_viewed_jobs: z.boolean().optional(),
});

export async function getSettings(): Promise<Settings> {
  const data = await request("/config/settings", SettingsSchemaLenient);
  return { ...data, external_apply_threshold: data.external_apply_threshold ?? 80, human_review_threshold: data.human_review_threshold ?? 85, skip_viewed_jobs: data.skip_viewed_jobs ?? true };
}

export async function updateSettings(data: Partial<Settings>): Promise<Settings> {
  const result = await request("/config/settings", SettingsSchemaLenient, {
    method: "PUT",
    body: JSON.stringify(data),
  });
  return { ...result, external_apply_threshold: result.external_apply_threshold ?? 80, human_review_threshold: result.human_review_threshold ?? 85, skip_viewed_jobs: result.skip_viewed_jobs ?? true };
}

export async function detectLanIp(signal?: AbortSignal): Promise<LanDetectResponse> {
  return request("/config/lan-detect", LanDetectResponseSchema, { signal });
}

// ---------------------------------------------------------------------------
// Schedule Configuration
// ---------------------------------------------------------------------------

export async function getScheduleConfig(): Promise<ScheduleConfigResponse> {
  return request("/config/schedule", ScheduleConfigResponseSchema);
}

export async function updateScheduleConfig(data: ScheduleConfigUpdate): Promise<ScheduleConfigResponse> {
  return request("/config/schedule", ScheduleConfigResponseSchema, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function getScheduleNext(): Promise<ScheduleNextResponse> {
  return request("/schedule/next", ScheduleNextResponseSchema);
}

// ---------------------------------------------------------------------------
// Chrome & Session Health
// ---------------------------------------------------------------------------

export async function getChromeStatus(): Promise<ChromeStatusResponse> {
  return request("/chrome/status", ChromeStatusResponseSchema);
}

export async function getSessionHealth(): Promise<SessionHealthResponse> {
  return request("/health/session", SessionHealthResponseSchema);
}

export async function launchChrome(): Promise<ChromeLaunchResponse> {
  return request("/chrome/launch", ChromeLaunchResponseSchema, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Ntfy Configuration
// ---------------------------------------------------------------------------

export async function getNtfyConfig(): Promise<NtfyConfigResponse> {
  return request("/config/ntfy", NtfyConfigResponseSchema);
}

export async function updateNtfyConfig(data: NtfyConfigUpdate): Promise<NtfyConfigResponse> {
  return request("/config/ntfy", NtfyConfigResponseSchema, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

// ---------------------------------------------------------------------------
// Ntfy Connection Test
// ---------------------------------------------------------------------------

export const NtfyTestResponseSchema = z.object({
  sent: z.boolean(),
  error: z.string().nullable().optional(),
  test_id: z.string().nullable().optional(),
});

export const NtfyTestStatusResponseSchema = z.object({
  confirmed: z.boolean(),
  confirmed_at: z.string().nullable().optional(),
  test_id: z.string().nullable().optional(),
});

export type NtfyTestResponse = z.infer<typeof NtfyTestResponseSchema>;
export type NtfyTestStatusResponse = z.infer<typeof NtfyTestStatusResponseSchema>;

export async function testNtfyConnection(): Promise<NtfyTestResponse> {
  return request("/config/ntfy/test", NtfyTestResponseSchema, { method: "POST" });
}

export async function getNtfyTestStatus(): Promise<NtfyTestStatusResponse> {
  return request("/config/ntfy/test/status", NtfyTestStatusResponseSchema);
}

// ---------------------------------------------------------------------------
// Preview Pipeline
// ---------------------------------------------------------------------------

export const PreviewJobOutSchema = z.object({
  job_id: z.string(),
  job_title: z.string(),
  company: z.string(),
  linkedin_url: z.string(),
  fit_score: z.number().int().nullable(),
  fit_rationale: z.string().nullable(),
  projected_action: z.string(),
  promoted: z.boolean(),
});

export const PreviewRunResponseSchema = z.object({
  id: z.string(),
  status: z.string(),
  started_at: z.string(),
  completed_at: z.string().nullable(),
  error_message: z.string().nullable(),
  total_discovered: z.number().int(),
  total_scored: z.number().int(),
  total_blacklisted: z.number().int(),
  jobs: z.array(PreviewJobOutSchema),
});

export const PreviewTriggerResponseSchema = z.object({
  run_id: z.string(),
  status: z.string(),
});

export const PromoteResponseSchema = z.object({
  promoted_ids: z.array(z.string()),
  count: z.number().int(),
});

export type PreviewJobOut = z.infer<typeof PreviewJobOutSchema>;
export type PreviewRunResponse = z.infer<typeof PreviewRunResponseSchema>;
export type PreviewTriggerResponse = z.infer<typeof PreviewTriggerResponseSchema>;
export type PromoteResponse = z.infer<typeof PromoteResponseSchema>;

export async function triggerPreview(): Promise<PreviewTriggerResponse> {
  return request("/preview", PreviewTriggerResponseSchema, { method: "POST" });
}

export async function getPreviewRun(runId: string): Promise<PreviewRunResponse> {
  return request(`/preview/${encodeURIComponent(runId)}`, PreviewRunResponseSchema);
}

export async function getLatestPreview(): Promise<PreviewTriggerResponse | null> {
  try {
    return await request("/preview/latest", PreviewTriggerResponseSchema);
  } catch (e) {
    if (e instanceof ApiError && e.status === 204) return null;
    throw e;
  }
}

export async function promotePreviewJobs(runId: string, jobIds: string[]): Promise<PromoteResponse> {
  return request(
    `/preview/${encodeURIComponent(runId)}/promote`,
    PromoteResponseSchema,
    { method: "POST", body: JSON.stringify({ job_ids: jobIds }) }
  );
}

// ---------------------------------------------------------------------------
// Job Records
// ---------------------------------------------------------------------------

export interface GetJobsParams {
  status?: string;
  search?: string;
  run_id?: string;
  min_score?: number;
  max_score?: number;
  page?: number;
  limit?: number;
}

const JobRecordOutSchemaLenient = JobRecordOutSchema.extend({
  tailored_resume_text: z.string().nullable().optional(),
  application_notes: z.string().nullable().optional(),
  run_id: z.string().nullable().optional(),
});

export async function getJobs(params?: GetJobsParams): Promise<JobRecordOut[]> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.search) query.set("search", params.search);
  if (params?.run_id) query.set("run_id", params.run_id);
  if (params?.min_score !== undefined) query.set("min_score", String(params.min_score));
  if (params?.max_score !== undefined) query.set("max_score", String(params.max_score));
  if (params?.page !== undefined) query.set("page", String(params.page));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));

  const qs = query.toString();
  const path = qs ? `/jobs?${qs}` : "/jobs";
  const data = await request(path, z.array(JobRecordOutSchemaLenient));
  return data.map((j) => ({
    ...j,
    tailored_resume_text: j.tailored_resume_text ?? null,
    application_notes: j.application_notes ?? null,
    run_id: j.run_id ?? null,
  } as JobRecordOut));
}

export async function getJob(id: string): Promise<JobRecordOut> {
  const data = await request(
    `/jobs/${encodeURIComponent(id)}`,
    JobRecordOutSchemaLenient
  );
  return {
    ...data,
    tailored_resume_text: data.tailored_resume_text ?? null,
    application_notes: data.application_notes ?? null,
    run_id: data.run_id ?? null,
  } as JobRecordOut;
}

export async function getJobStats(): Promise<StatsOut> {
  return request("/jobs/stats", StatsOutSchema);
}

// ---------------------------------------------------------------------------
// Human Queue
// ---------------------------------------------------------------------------

export async function getQueue(): Promise<QueueItemOut[]> {
  return request("/queue", z.array(QueueItemOutSchema));
}

export async function approveQueueItem(id: string): Promise<void> {
  return requestVoid(`/queue/${encodeURIComponent(id)}/approve`, { method: "POST" });
}

export async function skipQueueItem(id: string): Promise<void> {
  return requestVoid(`/queue/${encodeURIComponent(id)}/skip`, { method: "POST" });
}

export async function markApplied(id: string): Promise<void> {
  return requestVoid(`/queue/${encodeURIComponent(id)}/applied`, { method: "POST" });
}

export async function declineQueueItem(id: string): Promise<void> {
  return requestVoid(`/queue/${encodeURIComponent(id)}/decline`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Run History
// ---------------------------------------------------------------------------

export const RunHistoryItemSchema = z.object({
  id: z.string(),
  created_at: z.string(),
  summary: z.string(),
  claude_cost_usd: z.number().nullable().optional(),
});

export const RunHistoryResponseSchema = z.object({
  items: z.array(RunHistoryItemSchema),
});

export type RunHistoryItem = z.infer<typeof RunHistoryItemSchema>;
export type RunHistoryResponse = z.infer<typeof RunHistoryResponseSchema>;

export async function getRunHistory(limit: number = 5): Promise<RunHistoryItem[]> {
  const result = await request(
    `/runs/history?limit=${limit}`,
    RunHistoryResponseSchema
  );
  return result.items;
}

// ---------------------------------------------------------------------------
// Cost Stats
// ---------------------------------------------------------------------------

export const CostStatsSchema = z.object({
  today_usd: z.number(),
  last_7_days_usd: z.number(),
  last_30_days_usd: z.number(),
  all_time_usd: z.number(),
  per_run_avg_usd: z.number(),
});

export type CostStats = z.infer<typeof CostStatsSchema>;

export async function getCostStats(): Promise<CostStats> {
  return request("/runs/cost-stats", CostStatsSchema);
}



// ---------------------------------------------------------------------------
// Blacklist Configuration
// ---------------------------------------------------------------------------

export const BlacklistEntrySchema = z.object({
  value: z.string(),
  hit_count: z.number().int(),
});

export const BlacklistConfigResponseSchema = z.object({
  companies: z.array(BlacklistEntrySchema),
  title_patterns: z.array(BlacklistEntrySchema),
});

export type BlacklistEntry = z.infer<typeof BlacklistEntrySchema>;
export type BlacklistConfigResponse = z.infer<typeof BlacklistConfigResponseSchema>;

export async function getBlacklistConfig(): Promise<BlacklistConfigResponse> {
  return request("/config/blacklist", BlacklistConfigResponseSchema);
}

export async function addBlacklistCompany(value: string): Promise<void> {
  return requestVoid("/config/blacklist/companies", {
    method: "POST",
    body: JSON.stringify({ value }),
  });
}

export async function removeBlacklistCompany(entry: string): Promise<void> {
  return requestVoid(`/config/blacklist/companies/${encodeURIComponent(entry)}`, {
    method: "DELETE",
  });
}

export async function addBlacklistTitle(value: string): Promise<void> {
  return requestVoid("/config/blacklist/titles", {
    method: "POST",
    body: JSON.stringify({ value }),
  });
}

export async function removeBlacklistTitle(entry: string): Promise<void> {
  return requestVoid(`/config/blacklist/titles/${encodeURIComponent(entry)}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Scoring Trial
// ---------------------------------------------------------------------------

export const ScoringComparisonResponseSchema = z.object({
  id: z.number().int(),
  job_id: z.string(),
  job_title: z.string().nullable(),
  company: z.string().nullable(),
  local_score: z.number().int().nullable(),
  claude_score: z.number().int(),
  score_difference: z.number().int().nullable(),
  would_skip: z.boolean(),
  scored_at: z.string(),
});

export const PaginatedComparisonsSchema = z.object({
  items: z.array(ScoringComparisonResponseSchema),
  total: z.number().int(),
  page: z.number().int(),
  page_size: z.number().int(),
});

export type ScoringComparisonResponse = z.infer<typeof ScoringComparisonResponseSchema>;
export type PaginatedComparisons = z.infer<typeof PaginatedComparisonsSchema>;

export interface GetComparisonsParams {
  date_from?: string;
  date_to?: string;
  min_claude_score?: number;
  page?: number;
  page_size?: number;
}

export async function getScoringTrialComparisons(params?: GetComparisonsParams): Promise<PaginatedComparisons> {
  const query = new URLSearchParams();
  if (params?.date_from) query.set("date_from", params.date_from);
  if (params?.date_to) query.set("date_to", params.date_to);
  if (params?.min_claude_score !== undefined) query.set("min_claude_score", String(params.min_claude_score));
  if (params?.page !== undefined) query.set("page", String(params.page));
  if (params?.page_size !== undefined) query.set("page_size", String(params.page_size));

  const qs = query.toString();
  const path = qs ? `/scoring-trial/comparisons?${qs}` : "/scoring-trial/comparisons";
  return request(path, PaginatedComparisonsSchema);
}

// Scoring Trial — Status, Retrain, Config

export const ScoringTrialStatusSchema = z.object({
  model_trained: z.boolean(),
  training_samples_count: z.number().int(),
  model_version: z.string().nullable(),
  shadow_mode_active: z.boolean(),
  total_predictions_made: z.number().int(),
});

export const RetrainResponseSchema = z.object({
  success: z.boolean(),
  sample_count: z.number().int(),
  model_version: z.string(),
  duration_seconds: z.number(),
});

export const ScoringTrialConfigSchema = z.object({
  shadow_mode_enabled: z.boolean(),
  cutoff: z.number().int(),
});

export type ScoringTrialStatus = z.infer<typeof ScoringTrialStatusSchema>;
export type RetrainResponse = z.infer<typeof RetrainResponseSchema>;
export type ScoringTrialConfig = z.infer<typeof ScoringTrialConfigSchema>;

export interface ScoringTrialConfigUpdate {
  shadow_mode_enabled?: boolean;
  cutoff?: number;
}

export async function getScoringTrialStatus(): Promise<ScoringTrialStatus> {
  return request("/scoring-trial/status", ScoringTrialStatusSchema);
}

export async function triggerScoringTrialRetrain(): Promise<RetrainResponse> {
  return request("/scoring-trial/retrain", RetrainResponseSchema, { method: "POST" });
}

export async function updateScoringTrialConfig(data: ScoringTrialConfigUpdate): Promise<ScoringTrialConfig> {
  return request("/scoring-trial/config", ScoringTrialConfigSchema, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export const TrialMetricsResponseSchema = z.object({
  total_compared: z.number().int(),
  mean_absolute_error: z.number(),
  recall_at_cutoff: z.number(),
  false_positive_count: z.number().int(),
  cutoff: z.number().int(),
});

export type TrialMetricsResponse = z.infer<typeof TrialMetricsResponseSchema>;

export async function getScoringTrialMetrics(cutoff?: number): Promise<TrialMetricsResponse> {
  const query = new URLSearchParams();
  if (cutoff !== undefined) query.set("cutoff", String(cutoff));
  const qs = query.toString();
  const path = qs ? `/scoring-trial/metrics?${qs}` : "/scoring-trial/metrics";
  return request(path, TrialMetricsResponseSchema);
}

// ---------------------------------------------------------------------------
// Escalations
// ---------------------------------------------------------------------------

export const EscalationRecordOutSchema = z.object({
  id: z.string(),
  job_id: z.string(),
  tier: z.enum(["captcha", "human_review"]),
  form_state_snapshot: z.record(z.string(), z.unknown()),
  draft_answers: z.array(z.object({
    field_id: z.string(),
    question_text: z.string(),
    draft_answer: z.string(),
    edited_answer: z.string().nullable(),
  }).passthrough()).nullable(),
  timeout_deadline: z.string().nullable(),
  freshness_tier: z.string().nullable(),
  status: z.string(),
  resolution_method: z.string().nullable(),
  created_at: z.string(),
  resolved_at: z.string().nullable(),
  job_title: z.string().nullable(),
  company: z.string().nullable(),
  fit_score: z.number().int().nullable(),
});

export const EscalationListResponseSchema = z.object({
  escalations: z.array(EscalationRecordOutSchema),
  total: z.number().int(),
});

export type EscalationRecordOut = z.infer<typeof EscalationRecordOutSchema>;
export type EscalationListResponse = z.infer<typeof EscalationListResponseSchema>;

export async function getEscalations(includeResolved = false): Promise<EscalationListResponse> {
  const query = includeResolved ? "?include_resolved=true" : "";
  return request(`/escalations${query}`, EscalationListResponseSchema);
}

export async function getEscalation(id: string): Promise<EscalationRecordOut> {
  return request(`/escalations/${encodeURIComponent(id)}`, EscalationRecordOutSchema);
}

export async function submitEscalation(id: string, editedAnswers: Record<string, unknown>[]): Promise<EscalationRecordOut> {
  return request(`/escalations/${encodeURIComponent(id)}/submit`, EscalationRecordOutSchema, {
    method: "POST",
    body: JSON.stringify({ edited_answers: editedAnswers }),
  });
}

export async function skipEscalation(id: string): Promise<EscalationRecordOut> {
  return request(`/escalations/${encodeURIComponent(id)}/skip`, EscalationRecordOutSchema, {
    method: "POST",
  });
}

// ---------------------------------------------------------------------------
// Activity Logs
// ---------------------------------------------------------------------------

export const LogEntrySchema = z.object({
  job_id: z.string(),
  from_status: z.string().nullable(),
  to_status: z.string(),
  reason: z.string().nullable(),
  timestamp: z.string(),
});

export const LogsResponseSchema = z.object({
  entries: z.array(LogEntrySchema),
});

export type LogEntry = z.infer<typeof LogEntrySchema>;

export async function getActivityLog(limit: number = 50): Promise<LogEntry[]> {
  const result = await request(`/logs/activity?limit=${limit}`, LogsResponseSchema);
  return result.entries;
}
