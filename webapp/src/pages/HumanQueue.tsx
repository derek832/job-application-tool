import { useState, useEffect } from "react";
import {
  getQueue,
  approveQueueItem,
  rejectQueueItem,
  markManuallyApplied,
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
  }, []);

  async function handleAction(
    id: string,
    action: "approve" | "reject" | "manual"
  ) {
    setActionId(id);
    try {
      if (action === "approve") await approveQueueItem(id);
      else if (action === "reject") await rejectQueueItem(id);
      else await markManuallyApplied(id);
      setItems((prev) => prev.filter((item) => item.job_id !== id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setActionId(null);
    }
  }

  if (loading) return <LoadingSkeleton />;

  return (
    <div className="p-6 space-y-5">
      <h2 className="text-lg font-semibold text-gray-900">Review Queue</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {items.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <QueueCard
              key={item.job_id}
              item={item}
              disabled={actionId === item.job_id}
              onApprove={() => handleAction(item.job_id, "approve")}
              onReject={() => handleAction(item.job_id, "reject")}
              onManual={() => handleAction(item.job_id, "manual")}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface QueueCardProps {
  item: QueueItemOut;
  disabled: boolean;
  onApprove: () => void;
  onReject: () => void;
  onManual: () => void;
}

function QueueCard({ item, disabled, onApprove, onReject, onManual }: QueueCardProps): React.JSX.Element {
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
          <span className="shrink-0 inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-blue-50 text-blue-700">
            {item.fit_score}%
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 mb-3">
        {item.queue_reason && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700">
            {item.queue_reason}
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
          Approve
        </button>
        <button
          onClick={onReject}
          disabled={disabled}
          className="flex-1 px-3 py-1.5 text-xs font-medium text-red-700 bg-red-50 rounded-lg hover:bg-red-100 disabled:opacity-50 transition-colors"
        >
          Reject
        </button>
        <button
          onClick={onManual}
          disabled={disabled}
          className="flex-1 px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors"
        >
          Manual
        </button>
      </div>
    </div>
  );
}

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
