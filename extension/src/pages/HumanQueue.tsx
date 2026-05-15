import { useCallback, useEffect, useState } from "react";
import {
  type QueueItemOut,
  ApiError,
  getQueue,
  approveQueueItem,
  rejectQueueItem,
  markManuallyApplied,
} from "../api/client";

type ActionState = {
  loading: string | null;
  error: string | null;
};

export function HumanQueue() {
  const [items, setItems] = useState<QueueItemOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<ActionState>({ loading: null, error: null });

  const fetchQueue = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getQueue();
      setItems(data);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Failed to load queue items.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchQueue();
  }, [fetchQueue]);

  const handleAction = async (
    jobId: string,
    actionFn: (id: string) => Promise<void>,
    label: string
  ) => {
    setAction({ loading: jobId, error: null });
    try {
      await actionFn(jobId);
      await fetchQueue();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : `Failed to ${label} item.`;
      setAction({ loading: null, error: message });
      return;
    }
    setAction({ loading: null, error: null });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <p className="text-gray-500 text-sm">Loading queue…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <div className="rounded-md bg-red-50 p-4">
          <p className="text-sm text-red-700">{error}</p>
          <button
            onClick={() => void fetchQueue()}
            className="mt-2 text-sm font-medium text-red-600 hover:text-red-500"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-8">
        <p className="text-gray-500 text-sm">No items in the queue.</p>
        <p className="text-gray-400 text-xs mt-1">
          Jobs needing your review will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-3">
      <h1 className="text-lg font-semibold text-gray-900">Human Queue</h1>

      {action.error && (
        <div className="rounded-md bg-red-50 p-3">
          <p className="text-sm text-red-700">{action.error}</p>
        </div>
      )}

      <ul className="space-y-3">
        {items.map((item) => (
          <li
            key={item.job_id}
            className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="font-medium text-gray-900 truncate">
                  {item.job_title}
                </p>
                <p className="text-sm text-gray-600">{item.company}</p>
              </div>
              {item.fit_score !== null && (
                <span className="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800">
                  Score: {item.fit_score}
                </span>
              )}
            </div>

            <a
              href={item.linkedin_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-block text-sm text-blue-600 hover:text-blue-500 hover:underline truncate max-w-full"
            >
              {item.linkedin_url}
            </a>

            {item.queue_reason && (
              <p className="mt-1 text-xs text-gray-500">
                Reason: {item.queue_reason}
              </p>
            )}

            {item.fit_rationale && (
              <p className="mt-1 text-xs text-gray-500 line-clamp-2">
                {item.fit_rationale}
              </p>
            )}

            <p className="mt-1 text-xs text-gray-400">
              Added: {new Date(item.added_at).toLocaleString()}
            </p>

            <div className="mt-3 flex gap-2">
              <button
                onClick={() =>
                  void handleAction(item.job_id, approveQueueItem, "approve")
                }
                disabled={action.loading === item.job_id}
                className="rounded-md bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Approve
              </button>
              <button
                onClick={() =>
                  void handleAction(item.job_id, rejectQueueItem, "reject")
                }
                disabled={action.loading === item.job_id}
                className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Reject
              </button>
              <button
                onClick={() =>
                  void handleAction(item.job_id, markManuallyApplied, "mark as manual")
                }
                disabled={action.loading === item.job_id}
                className="rounded-md bg-gray-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Manual
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
