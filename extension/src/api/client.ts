/**
 * Typed Automator API client.
 *
 * Single module for all communication between the Chrome Extension and the
 * locally-hosted Automator service. Zod schemas mirror the Pydantic response
 * models defined in automator/src/api/schemas.py.
 */

import { z } from "zod";
import { loadToken } from "./token-storage";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = "http://127.0.0.1:7432";

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
  tailored_resume_pdf: z.string().nullable(),
  cover_letter_text: z.string().nullable(),
  error_message: z.string().nullable(),
  queue_reason: z.string().nullable(),
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
  backup_dir: z.string().nullable(),
  dry_run: z.boolean(),
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

// ---------------------------------------------------------------------------
// Internal Helpers
// ---------------------------------------------------------------------------

async function getToken(): Promise<string> {
  const token = await loadToken();
  if (!token) {
    throw new ApiError(0, "Unauthorized", "No API token configured in extension storage.");
  }
  return token;
}

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  options: RequestInit = {}
): Promise<T> {
  const token = await getToken();

  const url = `${BASE_URL}${path}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
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
  const token = await getToken();

  const url = `${BASE_URL}${path}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
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
  return request("/config/search", SearchConfigSchema);
}

export async function updateSearchConfig(data: SearchConfig): Promise<SearchConfig> {
  return request("/config/search", SearchConfigSchema, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function getGoalsProfile(): Promise<GoalsProfile> {
  return request("/config/goals", GoalsProfileSchema);
}

export async function updateGoalsProfile(data: GoalsProfile): Promise<GoalsProfile> {
  return request("/config/goals", GoalsProfileSchema, {
    method: "PUT",
    body: JSON.stringify(data),
  });
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

export async function getSettings(): Promise<Settings> {
  return request("/config/settings", SettingsSchema);
}

export async function updateSettings(data: Partial<Settings>): Promise<Settings> {
  return request("/config/settings", SettingsSchema, {
    method: "PUT",
    body: JSON.stringify(data),
  });
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

export async function getJobs(params?: GetJobsParams): Promise<JobRecordOut[]> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.search) query.set("search", params.search);
  if (params?.page !== undefined) query.set("page", String(params.page));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));

  const qs = query.toString();
  const path = qs ? `/jobs?${qs}` : "/jobs";
  return request(path, z.array(JobRecordOutSchema));
}

export async function getJob(id: string): Promise<JobRecordOut> {
  return request(`/jobs/${encodeURIComponent(id)}`, JobRecordOutSchema);
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
// Session Management
// ---------------------------------------------------------------------------

export async function importLinkedInCookies(): Promise<{ imported: number; message: string }> {
  // Get all LinkedIn cookies from multiple domain patterns
  const [dotLinkedin, wwwLinkedin, linkedinNoDot] = await Promise.all([
    chrome.cookies.getAll({ domain: ".linkedin.com" }),
    chrome.cookies.getAll({ domain: "www.linkedin.com" }),
    chrome.cookies.getAll({ domain: "linkedin.com" }),
  ]);

  // Deduplicate by name+domain+path
  const seen = new Set<string>();
  const cookies: chrome.cookies.Cookie[] = [];
  for (const c of [...dotLinkedin, ...wwwLinkedin, ...linkedinNoDot]) {
    const key = `${c.name}|${c.domain}|${c.path}`;
    if (!seen.has(key)) {
      seen.add(key);
      cookies.push(c);
    }
  }

  return request(
    "/session/cookies",
    z.object({ imported: z.number(), message: z.string() }),
    {
      method: "POST",
      body: JSON.stringify({ cookies }),
    }
  );
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
