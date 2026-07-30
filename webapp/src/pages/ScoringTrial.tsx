import { useState, useEffect, useCallback } from "react";
import {
  getScoringTrialComparisons,
  getScoringTrialMetrics,
  getScoringTrialStatus,
  triggerScoringTrialRetrain,
  updateScoringTrialConfig,
  ApiError,
} from "../api/client";
import type {
  ScoringComparisonResponse,
  PaginatedComparisons,
  TrialMetricsResponse,
  ScoringTrialStatus as ScoringTrialStatusType,
} from "../api/client";

const PAGE_SIZE = 25;
const DEFAULT_CUTOFF = 40;
const CLAUDE_GOOD_FIT_THRESHOLD = 65;

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isFalsePositive(row: ScoringComparisonResponse, cutoff: number): boolean {
  return (
    row.local_score !== null &&
    row.local_score < cutoff &&
    row.claude_score >= CLAUDE_GOOD_FIT_THRESHOLD
  );
}

export function ScoringTrial(): React.JSX.Element {
  const [data, setData] = useState<PaginatedComparisons | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [cutoff, setCutoff] = useState(DEFAULT_CUTOFF);
  const [metrics, setMetrics] = useState<TrialMetricsResponse | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(true);
  const [status, setStatus] = useState<ScoringTrialStatusType | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [retraining, setRetraining] = useState(false);
  const [retrainError, setRetrainError] = useState<string | null>(null);
  const [shadowToggling, setShadowToggling] = useState(false);
  const [shadowError, setShadowError] = useState<string | null>(null);

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  const fetchStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const result = await getScoringTrialStatus();
      setStatus(result);
    } catch {
      setStatus(null);
    } finally {
      setStatusLoading(false);
    }
  }, []);

  const fetchComparisons = useCallback(async () => {
    setLoading(true);
    try {
      setError(null);
      const result = await getScoringTrialComparisons({
        page,
        page_size: PAGE_SIZE,
      });
      setData(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load comparisons");
    } finally {
      setLoading(false);
    }
  }, [page]);

  const fetchMetrics = useCallback(async () => {
    setMetricsLoading(true);
    try {
      const result = await getScoringTrialMetrics(cutoff);
      setMetrics(result);
    } catch {
      // Metrics are non-critical — silently fail
      setMetrics(null);
    } finally {
      setMetricsLoading(false);
    }
  }, [cutoff]);

  async function handleRetrain() {
    setRetraining(true);
    setRetrainError(null);
    try {
      await triggerScoringTrialRetrain();
      await fetchStatus();
    } catch (e) {
      setRetrainError(e instanceof ApiError ? e.detail : "Retrain failed");
    } finally {
      setRetraining(false);
    }
  }

  async function handleShadowToggle() {
    if (!status) return;
    setShadowToggling(true);
    setShadowError(null);
    try {
      await updateScoringTrialConfig({
        shadow_mode_enabled: !status.shadow_mode_active,
      });
      await fetchStatus();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setShadowError("Cannot enable shadow mode — model not trained yet. Train the model first.");
      } else {
        setShadowError(e instanceof ApiError ? e.detail : "Failed to update shadow mode");
      }
    } finally {
      setShadowToggling(false);
    }
  }

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    fetchComparisons();
  }, [fetchComparisons]);

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-gray-900">Scoring Trial</h2>
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800 border border-amber-200">
          Temporary
        </span>
      </div>
      <p className="text-sm text-gray-500">
        Side-by-side comparison of local embedding scores vs Claude scores. False positives (local would skip, but Claude scores ≥65) are highlighted in red.
      </p>

      <ModelStatusPanel
        status={status}
        statusLoading={statusLoading}
        retraining={retraining}
        retrainError={retrainError}
        shadowToggling={shadowToggling}
        shadowError={shadowError}
        onRetrain={handleRetrain}
        onShadowToggle={handleShadowToggle}
      />

      <MetricsPanel
        metrics={metrics}
        metricsLoading={metricsLoading}
        cutoff={cutoff}
        onCutoffChange={setCutoff}
      />

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <LoadingSkeleton />
      ) : !data || data.items.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <ComparisonTable items={data.items} cutoff={cutoff} />
          <Pagination
            page={page}
            totalPages={totalPages}
            total={data.total}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}

function ModelStatusPanel({
  status,
  statusLoading,
  retraining,
  retrainError,
  shadowToggling,
  shadowError,
  onRetrain,
  onShadowToggle,
}: {
  status: ScoringTrialStatusType | null;
  statusLoading: boolean;
  retraining: boolean;
  retrainError: string | null;
  shadowToggling: boolean;
  shadowError: string | null;
  onRetrain: () => void;
  onShadowToggle: () => void;
}): React.JSX.Element {
  if (statusLoading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 animate-pulse">
        <div className="flex items-center justify-between">
          <div className="h-5 w-32 bg-gray-200 rounded" />
          <div className="h-8 w-28 bg-gray-200 rounded" />
        </div>
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-14 bg-gray-100 rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <p className="text-sm text-gray-500">Unable to load model status.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-900">Model Status</h3>
        <button
          onClick={onRetrain}
          disabled={retraining}
          className="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
        >
          {retraining && (
            <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          )}
          {retraining ? "Retraining…" : "Retrain Model"}
        </button>
      </div>

      {retrainError && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-700">
          {retrainError}
        </div>
      )}
      {shadowError && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-700">
          {shadowError}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-lg p-3 bg-gray-50 border border-gray-100">
          <p className="text-xs text-gray-500">Model</p>
          <p className="text-sm font-semibold text-gray-900">
            {status.model_trained ? (
              <span className="text-green-700">Trained</span>
            ) : (
              <span className="text-amber-700">Not Trained</span>
            )}
          </p>
        </div>
        <div className="rounded-lg p-3 bg-gray-50 border border-gray-100">
          <p className="text-xs text-gray-500">Training Samples</p>
          <p className="text-sm font-semibold text-gray-900">{status.training_samples_count}</p>
        </div>
        <div className="rounded-lg p-3 bg-gray-50 border border-gray-100">
          <p className="text-xs text-gray-500">Version</p>
          <p className="text-sm font-semibold text-gray-900">{status.model_version ?? "—"}</p>
        </div>
        <div className="rounded-lg p-3 bg-gray-50 border border-gray-100">
          <p className="text-xs text-gray-500">Predictions Made</p>
          <p className="text-sm font-semibold text-gray-900">{status.total_predictions_made}</p>
        </div>
      </div>

      <div className="flex items-center justify-between bg-gray-50 rounded-lg border border-gray-100 px-4 py-3">
        <div>
          <p className="text-sm font-medium text-gray-900">Shadow Mode</p>
          <p className="text-xs text-gray-500">
            {status.shadow_mode_active
              ? "Local scorer runs on every job alongside Claude"
              : "Local scoring is paused — no comparisons collected"}
          </p>
        </div>
        <button
          type="button"
          onClick={onShadowToggle}
          disabled={shadowToggling}
          className={`relative w-9 h-5 rounded-full transition-colors disabled:opacity-50 ${
            status.shadow_mode_active ? "bg-blue-600" : "bg-gray-300"
          }`}
          role="switch"
          aria-checked={status.shadow_mode_active}
          aria-label="Toggle shadow mode"
        >
          <span
            className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
              status.shadow_mode_active ? "translate-x-4" : "translate-x-0"
            }`}
          />
        </button>
      </div>
    </div>
  );
}

function MetricsPanel({
  metrics,
  metricsLoading,
  cutoff,
  onCutoffChange,
}: {
  metrics: TrialMetricsResponse | null;
  metricsLoading: boolean;
  cutoff: number;
  onCutoffChange: (value: number) => void;
}): React.JSX.Element {
  const insufficientData = metrics !== null && metrics.total_compared < 10;

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-900">Aggregate Metrics</h3>
        <div className="flex items-center gap-2">
          <label htmlFor="trial-cutoff" className="text-xs text-gray-600">
            Trial Cutoff
          </label>
          <input
            id="trial-cutoff"
            type="number"
            min={0}
            max={100}
            value={cutoff}
            onChange={(e) => {
              const val = parseInt(e.target.value, 10);
              if (!isNaN(val) && val >= 0 && val <= 100) {
                onCutoffChange(val);
              }
            }}
            className="w-16 px-2 py-1 text-xs border border-gray-200 rounded-lg text-center focus:outline-none focus:ring-2 focus:ring-amber-300 focus:border-amber-300"
          />
        </div>
      </div>

      {metricsLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 animate-pulse">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-14 bg-gray-100 rounded-lg" />
          ))}
        </div>
      ) : insufficientData ? (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-700">
          Insufficient data — at least 10 comparisons are needed before metrics are meaningful. Currently have {metrics?.total_compared ?? 0}.
        </div>
      ) : metrics ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricCard label="Total Compared" value={String(metrics.total_compared)} />
          <MetricCard label="MAE" value={metrics.mean_absolute_error.toFixed(1)} />
          <MetricCard
            label={`Recall @ ${metrics.cutoff}`}
            value={`${(metrics.recall_at_cutoff * 100).toFixed(1)}%`}
          />
          <MetricCard
            label={`False Positives @ ${metrics.cutoff}`}
            value={String(metrics.false_positive_count)}
            highlight={metrics.false_positive_count > 0}
          />
        </div>
      ) : (
        <div className="text-xs text-gray-400">Metrics unavailable</div>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}): React.JSX.Element {
  return (
    <div className={`rounded-lg p-3 ${highlight ? "bg-red-50 border border-red-200" : "bg-gray-50 border border-gray-100"}`}>
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`text-lg font-semibold ${highlight ? "text-red-700" : "text-gray-900"}`}>
        {value}
      </p>
    </div>
  );
}

function ComparisonTable({
  items,
  cutoff,
}: {
  items: ScoringComparisonResponse[];
  cutoff: number;
}): React.JSX.Element {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left px-4 py-3 font-medium text-gray-700">Job</th>
              <th className="text-left px-4 py-3 font-medium text-gray-700">Company</th>
              <th className="text-right px-4 py-3 font-medium text-gray-700">Local</th>
              <th className="text-right px-4 py-3 font-medium text-gray-700">Claude</th>
              <th className="text-right px-4 py-3 font-medium text-gray-700">Diff</th>
              <th className="text-right px-4 py-3 font-medium text-gray-700">Scored</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.map((row) => (
              <ComparisonRow key={row.id} row={row} cutoff={cutoff} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ComparisonRow({
  row,
  cutoff,
}: {
  row: ScoringComparisonResponse;
  cutoff: number;
}): React.JSX.Element {
  const fp = isFalsePositive(row, cutoff);

  return (
    <tr
      className={
        fp
          ? "bg-red-50 border-l-4 border-l-red-400"
          : "hover:bg-gray-50"
      }
    >
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          {fp && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700" title="False positive: local would skip but Claude scored ≥65">
              FP
            </span>
          )}
          <span className="text-gray-900 truncate max-w-[200px]">
            {row.job_title ?? "—"}
          </span>
        </div>
      </td>
      <td className="px-4 py-3 text-gray-600 truncate max-w-[150px]">
        {row.company ?? "—"}
      </td>
      <td className="px-4 py-3 text-right">
        {row.local_score !== null ? (
          <ScoreBadge score={row.local_score} dimmed={row.local_score < cutoff} />
        ) : (
          <span className="text-gray-400 text-xs">N/A</span>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        <ScoreBadge score={row.claude_score} />
      </td>
      <td className="px-4 py-3 text-right">
        {row.score_difference !== null ? (
          <DiffBadge diff={row.score_difference} />
        ) : (
          <span className="text-gray-400 text-xs">—</span>
        )}
      </td>
      <td className="px-4 py-3 text-right text-xs text-gray-500">
        {formatDateTime(row.scored_at)}
      </td>
    </tr>
  );
}

function ScoreBadge({ score, dimmed }: { score: number; dimmed?: boolean }): React.JSX.Element {
  const color =
    score >= 75
      ? "bg-green-100 text-green-800"
      : score >= 50
        ? "bg-yellow-100 text-yellow-800"
        : "bg-red-100 text-red-800";

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${color} ${dimmed ? "opacity-50" : ""}`}
    >
      {score}
    </span>
  );
}

function DiffBadge({ diff }: { diff: number }): React.JSX.Element {
  const abs = Math.abs(diff);
  let color = "text-gray-600";
  if (abs > 20) color = "text-red-600 font-medium";
  else if (abs > 10) color = "text-amber-600";

  return (
    <span className={`text-xs ${color}`}>
      {diff > 0 ? "+" : ""}
      {diff}
    </span>
  );
}

function Pagination({
  page,
  totalPages,
  total,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  total: number;
  onPageChange: (p: number) => void;
}): React.JSX.Element {
  return (
    <div className="flex items-center justify-between">
      <button
        onClick={() => onPageChange(Math.max(1, page - 1))}
        disabled={page === 1}
        className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        Previous
      </button>
      <span className="text-xs text-gray-500">
        Page {page} of {totalPages} ({total} total)
      </span>
      <button
        onClick={() => onPageChange(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        Next
      </button>
    </div>
  );
}

function EmptyState(): React.JSX.Element {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-8 text-center shadow-sm">
      <div className="w-12 h-12 rounded-full bg-amber-50 flex items-center justify-center mx-auto mb-3">
        <svg className="w-6 h-6 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
        </svg>
      </div>
      <p className="text-sm font-medium text-gray-900">No scoring comparisons yet</p>
      <p className="text-xs text-gray-500 mt-1">
        Comparisons will appear here once shadow mode is active and jobs are scored.
      </p>
    </div>
  );
}

function LoadingSkeleton(): React.JSX.Element {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden animate-pulse">
      <div className="bg-gray-50 border-b border-gray-200 px-4 py-3 flex gap-4">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="h-4 w-16 bg-gray-200 rounded" />
        ))}
      </div>
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="px-4 py-3 flex gap-4 border-b border-gray-100">
          <div className="h-4 w-40 bg-gray-200 rounded" />
          <div className="h-4 w-24 bg-gray-200 rounded" />
          <div className="h-4 w-10 bg-gray-200 rounded ml-auto" />
          <div className="h-4 w-10 bg-gray-200 rounded" />
          <div className="h-4 w-10 bg-gray-200 rounded" />
          <div className="h-4 w-20 bg-gray-200 rounded" />
        </div>
      ))}
    </div>
  );
}
