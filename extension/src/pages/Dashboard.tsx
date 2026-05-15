import { useCallback, useEffect, useState } from "react";
import {
  getStatus,
  triggerRun,
  pause,
  resume,
  ApiError,
  type StatusResponse,
} from "../api/client";

type SystemStatus = StatusResponse["status"];

function statusColor(status: SystemStatus): string {
  switch (status) {
    case "running":
      return "bg-green-500";
    case "paused":
      return "bg-yellow-500";
    case "idle":
      return "bg-gray-400";
    case "error":
      return "bg-red-500";
  }
}

function statusLabel(status: SystemStatus): string {
  switch (status) {
    case "running":
      return "Running";
    case "paused":
      return "Paused";
    case "idle":
      return "Idle";
    case "error":
      return "Error";
  }
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleString();
}

function formatRate(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

export default function Dashboard() {
  const [data, setData] = useState<StatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const status = await getStatus();
      setData(status);
      setError(null);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Unable to reach the Automator service.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  const handleRunNow = async () => {
    setActionLoading(true);
    try {
      await triggerRun();
      await fetchStatus();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      }
    } finally {
      setActionLoading(false);
    }
  };

  const handleTogglePause = async () => {
    if (!data) return;
    setActionLoading(true);
    try {
      if (data.status === "paused") {
        await resume();
      } else {
        await pause();
      }
      await fetchStatus();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      }
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <p className="text-sm text-gray-500">Loading dashboard...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-4">
        <div className="rounded-md bg-red-50 p-4">
          <p className="text-sm text-red-700">{error}</p>
          <button
            onClick={() => {
              setLoading(true);
              void fetchStatus();
            }}
            className="mt-2 text-sm font-medium text-red-600 hover:text-red-500"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const isPaused = data.status === "paused";

  return (
    <div className="space-y-4 p-4">
      {/* Status Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-3 w-3 rounded-full ${statusColor(data.status)}`}
          />
          <span className="text-sm font-medium text-gray-900">
            {statusLabel(data.status)}
          </span>
        </div>
        <span className="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800">
          Queue: {data.queue_count}
        </span>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="rounded-md bg-red-50 p-3">
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}

      {/* Run Times */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-md bg-gray-50 p-3">
          <p className="text-xs text-gray-500">Last Run</p>
          <p className="text-sm font-medium text-gray-900">
            {formatTimestamp(data.last_run_at)}
          </p>
        </div>
        <div className="rounded-md bg-gray-50 p-3">
          <p className="text-xs text-gray-500">Next Run</p>
          <p className="text-sm font-medium text-gray-900">
            {formatTimestamp(data.next_run_at)}
          </p>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="rounded-md border border-gray-200 p-3">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          Statistics
        </h3>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-600">Discovered</span>
            <span className="font-medium text-gray-900">
              {data.stats.total_discovered}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-600">Applied</span>
            <span className="font-medium text-gray-900">
              {data.stats.total_applied}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-600">Skipped</span>
            <span className="font-medium text-gray-900">
              {data.stats.total_skipped}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-600">Pending Review</span>
            <span className="font-medium text-gray-900">
              {data.stats.total_pending_review}
            </span>
          </div>
          <div className="col-span-2 flex justify-between border-t border-gray-100 pt-2">
            <span className="text-gray-600">Success Rate</span>
            <span className="font-medium text-gray-900">
              {formatRate(data.stats.application_success_rate)}
            </span>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2">
        <button
          onClick={() => void handleRunNow()}
          disabled={actionLoading || isPaused}
          className="flex-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {actionLoading ? "..." : "Run Now"}
        </button>
        <button
          onClick={() => void handleTogglePause()}
          disabled={actionLoading}
          className={`flex-1 rounded-md px-3 py-2 text-sm font-medium ${
            isPaused
              ? "bg-green-600 text-white hover:bg-green-700"
              : "bg-yellow-500 text-white hover:bg-yellow-600"
          } disabled:cursor-not-allowed disabled:opacity-50`}
        >
          {actionLoading ? "..." : isPaused ? "Resume" : "Pause"}
        </button>
      </div>
    </div>
  );
}
