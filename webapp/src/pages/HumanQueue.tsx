import { useState, useEffect } from "react";
import {
  getQueue,
  approveQueueItem,
  skipQueueItem,
  markApplied,
  declineQueueItem,
  ApiError,
} from "../api/client";
import type { QueueItemOut } from "../api/client";

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function HumanQueue(): React.JSX.Element {
  const [items, setItems] = useState<QueueItemOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  async function fetchQueue() {
    try {
      setError(null);
      const data = await getQueue();
      setItems(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load queue");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchQueue();
    // Poll every 15s to catch background tailoring completions
    const interval = setInterval(fetchQueue, 15_000);
    return () => clearInterval(interval);
  }, []);

  function showToast(message: string) {
    setToast(message);
    setTimeout(() => setToast(null), 4000);
  }

  async function handleApprove(id: string, title: string) {
    setActionId(id);
    try {
      await approveQueueItem(id);
      setItems((prev) => prev.filter((item) => item.job_id !== id));
      showToast(`"${title}" approved — tailoring in progress...`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setActionId(null);
    }
  }

  async function handleSkip(id: string) {
    setActionId(id);
    try {
      await skipQueueItem(id);
      setItems((prev) => prev.filter((item) => item.job_id !== id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setActionId(null);
    }
  }

  async function handleApplied(id: string) {
    setActionId(id);
    try {
      await markApplied(id);
      setItems((prev) => prev.filter((item) => item.job_id !== id));
      showToast("Marked as applied ✓");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setActionId(null);
    }
  }

  async function handleDecline(id: string) {
    setActionId(id);
    try {
      await declineQueueItem(id);
      setItems((prev) => prev.filter((item) => item.job_id !== id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setActionId(null);
    }
  }

  if (loading) return <LoadingSkeleton />;

  const readyToApply = items.filter((i) => i.status === "tailored");
  const needsReview = items.filter((i) => i.status === "scored");

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">Review Queue</h2>

      {toast && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-sm text-green-700 animate-fade-in">
          {toast}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {items.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          {/* Ready to Apply Section */}
          {readyToApply.length > 0 && (
            <section>
              <h3 className="text-sm font-medium text-gray-700 mb-3 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-green-500" />
                Ready to Apply ({readyToApply.length})
              </h3>
              <div className="space-y-3">
                {readyToApply.map((item) => (
                  <ReadyCard
                    key={item.job_id}
                    item={item}
                    disabled={actionId === item.job_id}
                    onApplied={() => handleApplied(item.job_id)}
                    onDecline={() => handleDecline(item.job_id)}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Needs Review Section */}
          {needsReview.length > 0 && (
            <section>
              <h3 className="text-sm font-medium text-gray-700 mb-3 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-amber-500" />
                Needs Review ({needsReview.length})
              </h3>
              <div className="space-y-3">
                {needsReview.map((item) => (
                  <ReviewCard
                    key={item.job_id}
                    item={item}
                    disabled={actionId === item.job_id}
                    onApprove={() => handleApprove(item.job_id, item.job_title)}
                    onSkip={() => handleSkip(item.job_id)}
                  />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ready to Apply card — job is tailored, PDF ready
// ---------------------------------------------------------------------------

interface ReadyCardProps {
  item: QueueItemOut;
  disabled: boolean;
  onApplied: () => void;
  onDecline: () => void;
}

function ReadyCard({ item, disabled, onApplied, onDecline }: ReadyCardProps): React.JSX.Element {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-white rounded-xl border border-green-100 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0 flex-1">
          <a
            href={item.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-semibold text-blue-700 hover:text-blue-900 hover:underline truncate block"
          >
            {item.job_title}
          </a>
          <p className="text-xs text-gray-500 mt-0.5">{item.company}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {item.fit_score !== null && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-green-50 text-green-700">
              {item.fit_score}%
            </span>
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1 text-gray-400 hover:text-gray-600 transition-colors"
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            <svg
              className={`w-4 h-4 transition-transform ${expanded ? "rotate-180" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="space-y-3 mb-3">
          {item.fit_rationale && (
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="text-xs font-medium text-gray-700 mb-1">Scoring Rationale</p>
              <p className="text-xs text-gray-600 leading-relaxed">{item.fit_rationale}</p>
            </div>
          )}

          {item.tailored_resume_text && (
            <TailoringDetails replacementsJson={item.tailored_resume_text} />
          )}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-2">
        {item.tailored_resume_pdf && (
          <a
            href={`/api/jobs/${item.job_id}/pdf`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-700 bg-blue-50 rounded-lg hover:bg-blue-100 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            PDF
          </a>
        )}
        <button
          onClick={onApplied}
          disabled={disabled}
          className="flex-1 px-3 py-1.5 text-xs font-medium text-green-700 bg-green-50 rounded-lg hover:bg-green-100 disabled:opacity-50 transition-colors"
        >
          Applied ✓
        </button>
        <button
          onClick={onDecline}
          disabled={disabled}
          className="px-3 py-1.5 text-xs font-medium text-gray-500 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors"
        >
          Decline
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Needs Review card — threshold/stretch job, needs approval or skip
// ---------------------------------------------------------------------------

interface ReviewCardProps {
  item: QueueItemOut;
  disabled: boolean;
  onApprove: () => void;
  onSkip: () => void;
}

function ReviewCard({ item, disabled, onApprove, onSkip }: ReviewCardProps): React.JSX.Element {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <a
            href={item.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-semibold text-blue-700 hover:text-blue-900 hover:underline truncate block"
          >
            {item.job_title}
          </a>
          <p className="text-xs text-gray-500 mt-0.5">{item.company}</p>
        </div>
        {item.fit_score !== null && (
          <span className="shrink-0 inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-amber-50 text-amber-700">
            {item.fit_score}%
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 mb-3">
        {item.queue_reason && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700">
            {item.queue_reason === "stretch_role" ? "Stretch Role" : "Threshold Score"}
          </span>
        )}
        <span className="text-xs text-gray-400">{formatTime(item.added_at)}</span>
      </div>

      {item.fit_rationale && (
        <div className="bg-gray-50 rounded-lg p-3 mb-3">
          <p className="text-xs text-gray-600 leading-relaxed">{item.fit_rationale}</p>
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          onClick={onApprove}
          disabled={disabled}
          className="flex-1 px-3 py-1.5 text-xs font-medium text-green-700 bg-green-50 rounded-lg hover:bg-green-100 disabled:opacity-50 transition-colors"
        >
          Approve & Tailor
        </button>
        <button
          onClick={onSkip}
          disabled={disabled}
          className="flex-1 px-3 py-1.5 text-xs font-medium text-gray-500 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors"
        >
          Skip
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state and loading
// ---------------------------------------------------------------------------

function EmptyState(): React.JSX.Element {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-8 text-center shadow-sm">
      <div className="w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center mx-auto mb-3">
        <svg className="w-6 h-6 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <p className="text-sm font-medium text-gray-900">All caught up</p>
      <p className="text-xs text-gray-500 mt-1">No items need your review right now.</p>
    </div>
  );
}

function LoadingSkeleton(): React.JSX.Element {
  return (
    <div className="p-6 space-y-5 animate-pulse">
      <div className="h-5 w-32 bg-gray-200 rounded" />
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-28 bg-gray-200 rounded-xl" />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tailoring details — shows ATS find/replace edits
// ---------------------------------------------------------------------------

function TailoringDetails({ replacementsJson }: { replacementsJson: string }): React.JSX.Element {
  const [showAll, setShowAll] = useState(false);

  let replacements: Array<{ find: string; replace: string }> = [];
  try {
    replacements = JSON.parse(replacementsJson);
  } catch {
    return (
      <div className="bg-amber-50 rounded-lg p-3">
        <p className="text-xs text-amber-700">Could not parse ATS optimizations</p>
      </div>
    );
  }

  if (!Array.isArray(replacements) || replacements.length === 0) return <></>;

  const visible = showAll ? replacements : replacements.slice(0, 3);

  return (
    <div className="bg-blue-50 rounded-lg p-3">
      <p className="text-xs font-medium text-blue-800 mb-2">
        ATS Optimizations ({replacements.length} changes)
      </p>
      <div className="space-y-1.5">
        {visible.map((r, i) => (
          <div key={i} className="text-xs">
            <span className="text-red-600 line-through">{r.find}</span>
            <span className="text-gray-400 mx-1">→</span>
            <span className="text-green-700 font-medium">{r.replace}</span>
          </div>
        ))}
      </div>
      {replacements.length > 3 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="mt-2 text-xs text-blue-600 hover:underline"
        >
          {showAll ? "Show less" : `Show all ${replacements.length} changes`}
        </button>
      )}
    </div>
  );
}
