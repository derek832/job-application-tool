import { useState, useCallback, useEffect } from "react";
import { getPreviewRun, promotePreviewJobs, ApiError } from "../api/client";
import type { PreviewRunResponse, PreviewJobOut } from "../api/client";
import { usePolling } from "../hooks/usePolling";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PreviewResultsProps {
  runId: string | null;
  onBack?: () => void;
}

type ProjectedAction = "auto_apply" | "stretch_queue" | "skip" | "blacklisted";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ACTION_STYLES: Record<ProjectedAction, { bg: string; text: string; label: string }> = {
  auto_apply: { bg: "bg-green-50", text: "text-green-700", label: "Auto Apply" },
  stretch_queue: { bg: "bg-yellow-50", text: "text-yellow-700", label: "Stretch Queue" },
  skip: { bg: "bg-red-50", text: "text-red-700", label: "Skip" },
  blacklisted: { bg: "bg-gray-100", text: "text-gray-500", label: "Blacklisted" },
};

const STATUS_LABELS: Record<string, string> = {
  running: "Running…",
  completed: "Completed",
  failed: "Failed",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PreviewResults({ runId, onBack }: PreviewResultsProps): React.JSX.Element {
  const [data, setData] = useState<PreviewRunResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [promoting, setPromoting] = useState(false);
  const [promoteSuccess, setPromoteSuccess] = useState<string | null>(null);

  const fetchRun = useCallback(async () => {
    if (!runId) return;
    try {
      setError(null);
      const run = await getPreviewRun(runId);
      setData(run);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load preview results");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  // Poll while the run is still in progress
  const isRunning = data?.status === "running";
  usePolling(fetchRun, 5_000, isRunning);

  // Initial fetch
  useEffect(() => {
    if (!runId) {
      setLoading(false);
      setError("No preview run ID provided");
      return;
    }
    fetchRun();
  }, [fetchRun, runId]);

  // ---------------------------------------------------------------------------
  // Selection handlers
  // ---------------------------------------------------------------------------

  function toggleSelection(jobId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) {
        next.delete(jobId);
      } else {
        next.add(jobId);
      }
      return next;
    });
  }

  function toggleSelectAll() {
    if (!data) return;
    const promotableJobs = data.jobs.filter((j) => !j.promoted);
    if (selectedIds.size === promotableJobs.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(promotableJobs.map((j) => j.job_id)));
    }
  }

  // ---------------------------------------------------------------------------
  // Promote handler
  // ---------------------------------------------------------------------------

  async function handlePromote() {
    if (selectedIds.size === 0 || !data || !runId) return;
    setPromoting(true);
    setPromoteSuccess(null);
    try {
      const result = await promotePreviewJobs(runId, Array.from(selectedIds));
      setPromoteSuccess(`${result.count} job${result.count !== 1 ? "s" : ""} approved for apply`);
      setSelectedIds(new Set());
      // Refresh data to reflect promoted state
      await fetchRun();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to promote jobs");
    } finally {
      setPromoting(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render states
  // ---------------------------------------------------------------------------

  if (loading) return <LoadingSkeleton />;

  if (error && !data) {
    return (
      <div className="p-6">
        {onBack && <BackButton onClick={onBack} />}
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          {error}
        </div>
      </div>
    );
  }

  if (!data) return <div />;

  const promotableJobs = data.jobs.filter((j) => !j.promoted);
  const allSelected = promotableJobs.length > 0 && selectedIds.size === promotableJobs.length;

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {onBack && <BackButton onClick={onBack} />}
          <h2 className="text-lg font-semibold text-gray-900">Preview Results</h2>
          <StatusBadge status={data.status} />
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Success banner */}
      {promoteSuccess && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-sm text-green-700">
          {promoteSuccess}
        </div>
      )}

      {/* Run failure message */}
      {data.status === "failed" && data.error_message && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          <p className="font-medium mb-1">Preview run failed</p>
          <p>{data.error_message}</p>
        </div>
      )}

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Discovered" value={data.total_discovered} />
        <StatCard label="Scored" value={data.total_scored} />
        <StatCard label="Blacklisted" value={data.total_blacklisted} />
      </div>

      {/* Action bar */}
      {data.status === "completed" && promotableJobs.length > 0 && (
        <div className="flex items-center justify-between bg-white rounded-xl border border-gray-200 p-3 shadow-sm">
          <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleSelectAll}
              className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Select all ({promotableJobs.length})
          </label>
          <button
            onClick={handlePromote}
            disabled={selectedIds.size === 0 || promoting}
            className="px-4 py-2 text-xs font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {promoting
              ? "Promoting…"
              : `Approve for Apply (${selectedIds.size})`}
          </button>
        </div>
      )}

      {/* Jobs table */}
      {data.jobs.length === 0 && data.status === "completed" ? (
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm text-center">
          <p className="text-sm text-gray-500">No new jobs discovered in this preview run.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="w-10 px-3 py-2" />
                  <th className="text-left px-3 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Title
                  </th>
                  <th className="text-left px-3 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Company
                  </th>
                  <th className="text-center px-3 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Fit Score
                  </th>
                  <th className="text-center px-3 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Projected Action
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.jobs.map((job) => (
                  <PreviewJobRow
                    key={job.job_id}
                    job={job}
                    selected={selectedIds.has(job.job_id)}
                    onToggle={() => toggleSelection(job.job_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Running indicator */}
      {isRunning && (
        <div className="flex items-center justify-center gap-2 text-sm text-gray-500 py-4">
          <Spinner />
          <span>Preview pipeline is running… results will appear as jobs are scored.</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PreviewJobRow({
  job,
  selected,
  onToggle,
}: {
  job: PreviewJobOut;
  selected: boolean;
  onToggle: () => void;
}): React.JSX.Element {
  const action = job.projected_action as ProjectedAction;
  const style = ACTION_STYLES[action] ?? ACTION_STYLES.skip;

  return (
    <tr className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
      <td className="px-3 py-2.5 text-center">
        {job.promoted ? (
          <span className="text-green-500" title="Promoted">✓</span>
        ) : (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            aria-label={`Select ${job.job_title} at ${job.company}`}
          />
        )}
      </td>
      <td className="px-3 py-2.5">
        <a
          href={job.linkedin_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 hover:underline font-medium"
        >
          {job.job_title}
        </a>
      </td>
      <td className="px-3 py-2.5 text-gray-700">{job.company}</td>
      <td className="px-3 py-2.5 text-center">
        {job.fit_score !== null ? (
          <FitScoreBadge score={job.fit_score} />
        ) : (
          <span className="text-gray-400">—</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-center">
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${style.bg} ${style.text}`}
        >
          {style.label}
        </span>
      </td>
    </tr>
  );
}

function FitScoreBadge({ score }: { score: number }): React.JSX.Element {
  let color = "text-red-600";
  if (score >= 70) color = "text-green-600";
  else if (score >= 50) color = "text-yellow-600";

  return <span className={`font-semibold ${color}`}>{score}</span>;
}

function StatusBadge({ status }: { status: string }): React.JSX.Element {
  const colors: Record<string, string> = {
    running: "bg-yellow-50 text-yellow-700",
    completed: "bg-green-50 text-green-700",
    failed: "bg-red-50 text-red-700",
  };

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] ?? "bg-gray-100 text-gray-600"}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function StatCard({ label, value }: { label: string; value: number }): React.JSX.Element {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-2xl font-semibold text-gray-900">{value}</p>
    </div>
  );
}

function BackButton({ onClick }: { onClick: () => void }): React.JSX.Element {
  return (
    <button
      onClick={onClick}
      className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
      aria-label="Back to dashboard"
    >
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
      </svg>
    </button>
  );
}

function Spinner(): React.JSX.Element {
  return (
    <svg className="w-4 h-4 animate-spin text-blue-500" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function LoadingSkeleton(): React.JSX.Element {
  return (
    <div className="p-6 space-y-5 animate-pulse">
      <div className="h-5 w-40 bg-gray-200 rounded" />
      <div className="grid grid-cols-3 gap-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 bg-gray-200 rounded-xl" />
        ))}
      </div>
      <div className="h-12 bg-gray-200 rounded-xl" />
      <div className="h-64 bg-gray-200 rounded-xl" />
    </div>
  );
}
