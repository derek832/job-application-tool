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
  skip_viewed_jobs: z.boolean().optional(),
});

export async function getSettings(): Promise<Settings> {
  const data = await request("/config/settings", SettingsSchemaLenient);
  return { ...data, external_apply_threshold: data.external_apply_threshold ?? 80, skip_viewed_jobs: data.skip_viewed_jobs ?? true };
}

export async function updateSettings(data: Partial<Settings>): Promise<Settings> {
  const result = await request("/config/settings", SettingsSchemaLenient, {
    method: "PUT",
    body: JSON.stringify(data),
  });
  return { ...result, external_apply_threshold: result.external_apply_threshold ?? 80, skip_viewed_jobs: result.skip_viewed_jobs ?? true };
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
  page?: number;
  limit?: number;
}

const JobRecordOutSchemaLenient = JobRecordOutSchema.extend({
  tailored_resume_text: z.string().nullable().optional(),
  application_notes: z.string().nullable().optional(),
});

export async function getJobs(params?: GetJobsParams): Promise<JobRecordOut[]> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.search) query.set("search", params.search);
  if (params?.page !== undefined) query.set("page", String(params.page));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));

  const qs = query.toString();
  const path = qs ? `/jobs?${qs}` : "/jobs";
  const data = await request(path, z.array(JobRecordOutSchemaLenient));
  return data.map((j) => ({
    ...j,
    tailored_resume_text: j.tailored_resume_text ?? null,
    application_notes: j.application_notes ?? null,
  }));
}

export async function getJob(id: string): Promise<JobRecordOut> {
  const data = await request(
    `/jobs/${encodeURIComponent(id)}`,
    JobRecordOutSchemaLenient
  );
  return { ...data, tailored_resume_text: data.tailored_resume_text ?? null, application_notes: data.application_notes ?? null };
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

export async function rejectQueueItem(id: string): Promise<void> {
  return requestVoid(`/queue/${encodeURIComponent(id)}/reject`, { method: "POST" });
}

export async function markManuallyApplied(id: string): Promise<void> {
  return requestVoid(`/queue/${encodeURIComponent(id)}/manual`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Run History
// ---------------------------------------------------------------------------

export const RunHistoryItemSchema = z.object({
  id: z.string(),
  created_at: z.string(),
  summary: z.string(),
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
