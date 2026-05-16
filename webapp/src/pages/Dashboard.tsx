import { useState, useCallback } from "react";
import { getStatus, getActivityLog, triggerRun, pause, resume, ApiError } from "../api/client";
import type { StatusResponse, LogEntry } from "../api/client";
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

export function Dashboard(): React.JSX.Element {
  const [data, setData] = useState<StatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [activityLog, setActivityLog] = useState<LogEntry[]>([]);

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

  const pollCallback = useCallback(() => {
    fetchStatus();
    fetchLog();
  }, [fetchStatus, fetchLog]);

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
              onClick={handleTogglePause}
              disabled={actionLoading}
              className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors"
            >
              {data.status === "paused" ? "Resume" : "Pause"}
            </button>
          </div>
        </div>
      </div>

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
