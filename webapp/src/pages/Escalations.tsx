import { useState, useEffect, useCallback } from "react";
import { getEscalations, ApiError } from "../api/client";
import type { EscalationRecordOut } from "../api/client";

/**
 * Escalation list page — displays pending escalations sorted by urgency.
 *
 * Color-coded urgency:
 * - Red: < 15 minutes remaining
 * - Amber: < 1 hour remaining
 * - Green: > 1 hour remaining
 *
 * Validates: Requirements 6.1, 6.5
 */

interface EscalationsProps {
  onSelectEscalation?: (id: string) => void;
}

export function Escalations({ onSelectEscalation }: EscalationsProps): React.JSX.Element {
  const [escalations, setEscalations] = useState<EscalationRecordOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchEscalations = useCallback(async () => {
    try {
      setError(null);
      const data = await getEscalations();
      setEscalations(data.escalations);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load escalations");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEscalations();
  }, [fetchEscalations]);

  // Refresh every 30 seconds to keep countdown timers accurate
  useEffect(() => {
    const interval = setInterval(fetchEscalations, 30_000);
    return () => clearInterval(interval);
  }, [fetchEscalations]);

  if (loading) return <LoadingSkeleton />;

  return (
    <div className="p-6 space-y-5">
      <h2 className="text-lg font-semibold text-gray-900">Escalations</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {escalations.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-3">
          {escalations.map((item) => (
            <EscalationCard
              key={item.id}
              item={item}
              onSelect={() => onSelectEscalation?.(item.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Escalation Card
// ---------------------------------------------------------------------------

interface EscalationCardProps {
  item: EscalationRecordOut;
  onSelect: () => void;
}

function EscalationCard({ item, onSelect }: EscalationCardProps): React.JSX.Element {
  const urgency = getUrgencyLevel(item.timeout_deadline);
  const timeRemaining = formatTimeRemaining(item.timeout_deadline);

  return (
    <button
      onClick={onSelect}
      className="w-full text-left bg-white rounded-xl border border-gray-200 p-4 shadow-sm hover:border-blue-300 hover:shadow-md transition-all"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">
            {item.job_title ?? "Unknown Position"}
          </p>
          <p className="text-xs text-gray-500 mt-0.5">
            {item.company ?? "Unknown Company"}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {item.fit_score !== null && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-blue-50 text-blue-700">
              {item.fit_score}%
            </span>
          )}
          <TierBadge tier={item.tier} />
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {item.freshness_tier && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
              {item.freshness_tier}
            </span>
          )}
        </div>
        {timeRemaining && (
          <CountdownBadge urgency={urgency} timeRemaining={timeRemaining} />
        )}
        {item.tier === "captcha" && (
          <span className="text-xs text-gray-500">No timeout</span>
        )}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TierBadge({ tier }: { tier: "captcha" | "human_review" }): React.JSX.Element {
  if (tier === "captcha") {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-50 text-purple-700">
        CAPTCHA
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-50 text-indigo-700">
      Review
    </span>
  );
}

type UrgencyLevel = "red" | "amber" | "green" | "none";

function CountdownBadge({
  urgency,
  timeRemaining,
}: {
  urgency: UrgencyLevel;
  timeRemaining: string;
}): React.JSX.Element {
  const colorClasses: Record<UrgencyLevel, string> = {
    red: "bg-red-50 text-red-700 border-red-200",
    amber: "bg-amber-50 text-amber-700 border-amber-200",
    green: "bg-green-50 text-green-700 border-green-200",
    none: "bg-gray-50 text-gray-600 border-gray-200",
  };

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border ${colorClasses[urgency]}`}
    >
      <ClockIcon />
      {timeRemaining}
    </span>
  );
}

function ClockIcon(): React.JSX.Element {
  return (
    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
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
      <p className="text-sm font-medium text-gray-900">No pending escalations</p>
      <p className="text-xs text-gray-500 mt-1">All applications are proceeding normally.</p>
    </div>
  );
}

function LoadingSkeleton(): React.JSX.Element {
  return (
    <div className="p-6 space-y-5 animate-pulse">
      <div className="h-5 w-36 bg-gray-200 rounded" />
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-24 bg-gray-200 rounded-xl" />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Utility functions
// ---------------------------------------------------------------------------

/**
 * Determine urgency level based on time remaining until deadline.
 * - Red: < 15 minutes
 * - Amber: < 1 hour
 * - Green: > 1 hour
 */
function getUrgencyLevel(timeoutDeadline: string | null): UrgencyLevel {
  if (!timeoutDeadline) return "none";

  const deadline = new Date(timeoutDeadline);
  const now = new Date();
  const diffMs = deadline.getTime() - now.getTime();

  if (diffMs <= 0) return "red";
  if (diffMs < 15 * 60 * 1000) return "red";
  if (diffMs < 60 * 60 * 1000) return "amber";
  return "green";
}

/**
 * Format time remaining as a human-readable string.
 * Returns null if no deadline is set.
 */
function formatTimeRemaining(timeoutDeadline: string | null): string | null {
  if (!timeoutDeadline) return null;

  const deadline = new Date(timeoutDeadline);
  const now = new Date();
  const diffMs = deadline.getTime() - now.getTime();

  if (diffMs <= 0) return "Expired";

  const minutes = Math.floor(diffMs / (60 * 1000));
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;

  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    return `${days}d ${hours % 24}h`;
  }
  if (hours > 0) {
    return `${hours}h ${remainingMinutes}m`;
  }
  return `${minutes}m`;
}
