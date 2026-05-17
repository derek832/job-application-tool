import { useState, useCallback, useRef, useEffect } from "react";
import { getStatus, getActivityLog, getRunHistory, triggerRun, triggerPreview, getPreviewRun, pause, resume, getChromeStatus, getSessionHealth, ApiError } from "../api/client";
import type { StatusResponse, LogEntry, RunHistoryItem, ChromeStatusResponse, SessionHealthResponse } from "../api/client";
import { usePolling } from "../hooks/usePolling";

const STATUS_COLORS: Record<string, string> = {
  idle: "bg-green-500",
  running: "bg-yellow-500",
  paused: "bg-red-500",
  error: "bg-red-500",
};

const STATUS_LABELS: Record<string, string> = {
  idle: "Idle",
  running: "Running",
  paused: "Paused",
  error: "Error",
};

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRelativeTime(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diffMs = now - then;

  if (diffMs < 0) return "just now";

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return "just now";

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes === 1 ? "1 minute ago" : `${minutes} minutes ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;

  const days = Math.floor(hours / 24);
  if (days < 30) return days === 1 ? "1 day ago" : `${days} days ago`;

  const months = Math.floor(days / 30);
  return months === 1 ? "1 month ago" : `${months} months ago`;
}

interface DashboardProps {
  onPreviewComplete?: (runId: string) => void;
}

export function Dashboard({ onPreviewComplete }: DashboardProps): React.JSX.Element {
  const [data, setData] = useState<StatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [activityLog, setActivityLog] = useState<LogEntry[]>([]);
  const [runHistory, setRunHistory] = useState<RunHistoryItem[]>([]);
  const [chromeStatus, setChromeStatus] = useState<ChromeStatusResponse | null>(null);
  const [sessionHealth, setSessionHealth] = useState<SessionHealthResponse | null>(null);
  const [healthCheckLoading, setHealthCheckLoading] = useState(false);
  const [chromeCopied, setChromeCopied] = useState(false);
  const [previewStatus, setPreviewStatus] = useState<"idle" | "running" | "completed" | "failed">("idle");
  const [, setPreviewRunId] = useState<string | null>(null);
  const previewPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      setError(null);
      const status = await getStatus();
      setData(status);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load status");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchLog = useCallback(async () => {
    try {
      const entries = await getActivityLog(20);
      setActivityLog(entries);
    } catch {
      // Non-critical — don't show error for log fetch failures
    }
  }, []);

  const fetchRunHistory = useCallback(async () => {
    try {
      const items = await getRunHistory(5);
      setRunHistory(items);
    } catch {
      // Non-critical — don't show error for run history fetch failures
    }
  }, []);

  const fetchChromeStatus = useCallback(async () => {
    try {
      const status = await getChromeStatus();
      setChromeStatus(status);
    } catch {
      // Non-critical — Chrome may not be running
      setChromeStatus({ connected: false });
    }
  }, []);

  const pollCallback = useCallback(() => {
    fetchStatus();
    fetchLog();
    fetchRunHistory();
    fetchChromeStatus();
  }, [fetchStatus, fetchLog, fetchRunHistory, fetchChromeStatus]);

  // Poll status and activity log every 60 seconds
  usePolling(pollCallback, 60_000);

  async function handleRun() {
    setActionLoading(true);
    try {
      await triggerRun();
      await fetchStatus();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleTogglePause() {
    if (!data) return;
    setActionLoading(true);
    try {
      if (data.status === "paused") {
        await resume();
      } else {
        await pause();
      }
      await fetchStatus();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleCheckSessionHealth() {
    setHealthCheckLoading(true);
    try {
      const result = await getSessionHealth();
      setSessionHealth(result);
      // Also refresh chrome status since health check verifies Chrome
      setChromeStatus({ connected: result.chrome_reachable });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Health check failed");
    } finally {
      setHealthCheckLoading(false);
    }
  }

  async function handleLaunchChrome() {
    // Chrome runs on the host, not inside Docker. Point users to the batch file.
    try {
      await navigator.clipboard.writeText("start-chrome-debug.bat");
      setChromeCopied(true);
      setTimeout(() => setChromeCopied(false), 3000);
    } catch {
      // Fallback
    }
  }

  // Clean up preview polling on unmount
  useEffect(() => {
    return () => {
      if (previewPollRef.current) {
        clearInterval(previewPollRef.current);
      }
    };
  }, []);

  async function handlePreviewRun() {
    setActionLoading(true);
    setPreviewStatus("running");
    setError(null);
    try {
      const result = await triggerPreview();
      setPreviewRunId(result.run_id);

      // Start polling for preview completion
      previewPollRef.current = setInterval(async () => {
        try {
          const preview = await getPreviewRun(result.run_id);
          if (preview.status === "completed") {
            setPreviewStatus("completed");
            if (previewPollRef.current) {
              clearInterval(previewPollRef.current);
              previewPollRef.current = null;
            }
            // Navigate to preview results page
            onPreviewComplete?.(result.run_id);
          } else if (preview.status === "failed") {
            setPreviewStatus("failed");
            setError(preview.error_message ?? "Preview run failed");
            if (previewPollRef.current) {
              clearInterval(previewPollRef.current);
              previewPollRef.current = null;
            }
          }
        } catch {
          // Polling error — keep trying
        }
      }, 3000);
    } catch (e) {
      setPreviewStatus("failed");
      setError(e instanceof ApiError ? e.message : "Failed to start preview");
    } finally {
      setActionLoading(false);
    }
  }

  if (loading) return <LoadingSkeleton />;

  if (error && !data) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          {error}
        </div>
      </div>
    );
  }

  if (!data) return <div />;

  const stats = [
    { label: "Discovered", value: data.stats.total_discovered },
    { label: "Applied", value: data.stats.total_applied },
    { label: "Skipped", value: data.stats.total_skipped },
    { label: "Pending", value: data.stats.total_pending_review },
  ];

  const healthItems = [
    { label: "Claude API", ok: data.health.claude_api },
    { label: "Gmail", ok: data.health.gmail },
    { label: "Google Docs", ok: data.health.google_docs },
  ];

  return (
    <div className="p-6 space-y-5">
      <h2 className="text-lg font-semibold text-gray-900">Dashboard</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Status card */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={`w-2.5 h-2.5 rounded-full ${STATUS_COLORS[data.status]}`} />
            <span className="text-sm font-medium text-gray-900">
              {STATUS_LABELS[data.status]}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRun}
              disabled={actionLoading || data.status === "running"}
              className="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Run Now
            </button>
            <button
              onClick={handlePreviewRun}
              disabled={actionLoading || previewStatus === "running"}
              className="px-3 py-1.5 text-xs font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {previewStatus === "running" ? "Preview Running…" : "Preview Run"}
            </button>
            <button
              onClick={handleTogglePause}
              disabled={actionLoading}
              className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors"
            >
              {data.status === "paused" ? "Resume" : "Pause"}
            </button>
          </div>
        </div>
      </div>

      {/* Preview status indicator */}
      {previewStatus !== "idle" && (
        <div className={`rounded-xl border p-3 shadow-sm flex items-center gap-3 ${
          previewStatus === "running"
            ? "bg-purple-50 border-purple-200"
            : previewStatus === "completed"
            ? "bg-green-50 border-green-200"
            : "bg-red-50 border-red-200"
        }`}>
          {previewStatus === "running" && (
            <svg className="w-4 h-4 text-purple-600 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          )}
          {previewStatus === "completed" && (
            <span className="w-4 h-4 text-green-600">✓</span>
          )}
          {previewStatus === "failed" && (
            <span className="w-4 h-4 text-red-600">✗</span>
          )}
          <span className={`text-xs font-medium ${
            previewStatus === "running"
              ? "text-purple-700"
              : previewStatus === "completed"
              ? "text-green-700"
              : "text-red-700"
          }`}>
            {previewStatus === "running" && "Preview run in progress — discovering and scoring jobs…"}
            {previewStatus === "completed" && "Preview run completed — viewing results…"}
            {previewStatus === "failed" && "Preview run failed"}
          </span>
          {previewStatus !== "running" && (
            <button
              onClick={() => setPreviewStatus("idle")}
              className="ml-auto text-xs text-gray-400 hover:text-gray-600"
              aria-label="Dismiss"
            >
              ✕
            </button>
          )}
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3">
        {stats.map((s) => (
          <div key={s.label} className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <p className="text-xs text-gray-500 mb-1">{s.label}</p>
            <p className="text-2xl font-semibold text-gray-900">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Health indicators */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <p className="text-xs text-gray-500 mb-3">Service Health</p>
        <div className="flex gap-2">
          {healthItems.map((h) => (
            <span
              key={h.label}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                h.ok
                  ? "bg-green-50 text-green-700"
                  : "bg-red-50 text-red-700"
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${h.ok ? "bg-green-500" : "bg-red-500"}`} />
              {h.label}
            </span>
          ))}
        </div>
      </div>

      {/* Session Health & Chrome Status */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <p className="text-xs text-gray-500 mb-3">Session Health</p>
        <div className="flex flex-wrap gap-2 mb-3">
          {/* Chrome CDP Status */}
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
              chromeStatus?.connected
                ? "bg-green-50 text-green-700"
                : "bg-red-50 text-red-700"
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${chromeStatus?.connected ? "bg-green-500" : "bg-red-500"}`} />
            {chromeStatus?.connected ? "Chrome Connected" : "Chrome Not Connected"}
          </span>

          {/* LinkedIn Session Status */}
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
              sessionHealth?.linkedin_authenticated
                ? "bg-green-50 text-green-700"
                : "bg-gray-100 text-gray-600"
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${sessionHealth?.linkedin_authenticated ? "bg-green-500" : "bg-gray-400"}`} />
            {sessionHealth?.linkedin_authenticated ? "LinkedIn Authenticated" : "LinkedIn Unknown"}
          </span>
        </div>

        {/* Error message from last health check */}
        {sessionHealth?.error_message && (
          <p className="text-xs text-red-600 mb-3">{sessionHealth.error_message}</p>
        )}

        <div className="flex gap-2">
          <button
            onClick={handleCheckSessionHealth}
            disabled={healthCheckLoading}
            className="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {healthCheckLoading ? "Checking…" : "Check Session Health"}
          </button>

          {/* Show helper when Chrome is not connected */}
          {!chromeStatus?.connected && (
            <button
              onClick={handleLaunchChrome}
              className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
              title="Double-click start-chrome-debug.bat in the project root"
            >
              {chromeCopied ? "✓ Run start-chrome-debug.bat" : "How to Launch Chrome"}
            </button>
          )}
        </div>
      </div>

      {/* Timestamps */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-gray-500 mb-0.5">Last Run</p>
            <p className="text-sm font-medium text-gray-900">{formatTime(data.last_run_at)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-0.5">Next Run</p>
            <p className="text-sm font-medium text-gray-900">{formatTime(data.next_run_at)}</p>
          </div>
        </div>
      </div>

      {/* Run History */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <p className="text-xs text-gray-500 mb-3">Run History</p>
        {runHistory.length === 0 ? (
          <p className="text-xs text-gray-400">No runs have completed yet</p>
        ) : (
          <div className="space-y-2 max-h-60 overflow-y-auto">
            {runHistory.map((entry) => (
              <div key={entry.id} className="py-2 border-t border-gray-100 first:border-0">
                <p className="text-xs text-gray-400 mb-0.5">
                  {formatRelativeTime(entry.created_at)}
                </p>
                <p className="text-xs text-gray-700">{entry.summary}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Activity Log */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <p className="text-xs text-gray-500 mb-3">Recent Activity</p>
        {activityLog.length === 0 ? (
          <p className="text-xs text-gray-400">No activity yet</p>
        ) : (
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {activityLog.map((entry, i) => (
              <div key={i} className="flex items-start gap-2 text-xs py-1 border-t border-gray-100 first:border-0">
                <span className="text-gray-400 shrink-0 w-12">
                  {new Date(entry.timestamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                </span>
                <span className="text-gray-600 truncate">
                  <span className="font-medium text-gray-900">{entry.job_id.slice(0, 8)}</span>
                  {" → "}
                  <span className={entry.to_status === "applied" ? "text-green-600 font-medium" : entry.to_status.includes("failed") ? "text-red-600" : ""}>
                    {entry.to_status}
                  </span>
                  {entry.reason && <span className="text-gray-400"> · {entry.reason}</span>}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function LoadingSkeleton(): React.JSX.Element {
  return (
    <div className="p-6 space-y-5 animate-pulse">
      <div className="h-5 w-24 bg-gray-200 rounded" />
      <div className="h-16 bg-gray-200 rounded-xl" />
      <div className="grid grid-cols-2 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-20 bg-gray-200 rounded-xl" />
        ))}
      </div>
      <div className="h-16 bg-gray-200 rounded-xl" />
      <div className="h-16 bg-gray-200 rounded-xl" />
    </div>
  );
}
