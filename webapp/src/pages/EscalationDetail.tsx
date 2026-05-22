import { useState, useEffect } from "react";
import {
  getEscalation,
  submitEscalation,
  skipEscalation,
  ApiError,
} from "../api/client";
import type { EscalationRecordOut } from "../api/client";

interface EscalationDetailProps {
  escalationId: string | null;
  onBack: () => void;
}

interface FormField {
  field_id: string;
  label: string;
  value: string;
  type: string;
  selector?: string;
  is_open_ended?: boolean;
}

interface DraftAnswer {
  field_id: string;
  question_text: string;
  draft_answer: string;
  edited_answer: string | null;
}

export function EscalationDetail({ escalationId, onBack }: EscalationDetailProps): React.JSX.Element {
  const [escalation, setEscalation] = useState<EscalationRecordOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editedAnswers, setEditedAnswers] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!escalationId) {
      setLoading(false);
      setError("No escalation ID provided");
      return;
    }
    fetchEscalation(escalationId);
  }, [escalationId]);

  async function fetchEscalation(id: string) {
    try {
      setError(null);
      setLoading(true);
      const data = await getEscalation(id);
      setEscalation(data);

      // Initialize edited answers from draft answers
      const drafts = (data.draft_answers ?? []) as DraftAnswer[];
      const initial: Record<string, string> = {};
      for (const draft of drafts) {
        initial[draft.field_id] = draft.edited_answer ?? draft.draft_answer ?? "";
      }
      setEditedAnswers(initial);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load escalation");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit() {
    if (!escalation) return;
    setSubmitting(true);
    setActionError(null);
    try {
      const answers = Object.entries(editedAnswers).map(([field_id, edited_answer]) => ({
        field_id,
        edited_answer,
      }));
      await submitEscalation(escalation.id, answers);
      // Refresh to show resolved state
      await fetchEscalation(escalation.id);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Submit failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSkip() {
    if (!escalation) return;
    setSubmitting(true);
    setActionError(null);
    try {
      await skipEscalation(escalation.id);
      // Refresh to show resolved state
      await fetchEscalation(escalation.id);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Skip failed");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <LoadingSkeleton />;

  if (error || !escalation) {
    return (
      <div className="p-6 space-y-4">
        <BackButton onClick={onBack} />
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          {error ?? "Escalation not found"}
        </div>
      </div>
    );
  }

  const isPending = escalation.status === "pending";
  const snapshot = escalation.form_state_snapshot as {
    external_url?: string;
    fields?: FormField[];
    screenshot_path?: string;
    page_title?: string;
  };
  const fields = snapshot.fields ?? [];
  const draftAnswers = (escalation.draft_answers ?? []) as DraftAnswer[];
  const screenshotPath = snapshot.screenshot_path;

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BackButton onClick={onBack} />
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold text-gray-900 truncate">
            {escalation.job_title ?? "Escalation Review"}
          </h2>
          <p className="text-sm text-gray-500">
            {escalation.company ?? "Unknown company"}
            {escalation.fit_score !== null && (
              <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-blue-50 text-blue-700">
                {escalation.fit_score}%
              </span>
            )}
          </p>
        </div>
        <TierBadge tier={escalation.tier} />
        <StatusBadge status={escalation.status} />
      </div>

      {/* Resolution info for resolved records */}
      {!isPending && (
        <ResolutionBanner
          status={escalation.status}
          resolutionMethod={escalation.resolution_method}
          resolvedAt={escalation.resolved_at}
        />
      )}

      {/* Action error */}
      {actionError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      {/* Page screenshot */}
      {screenshotPath && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <h3 className="text-sm font-medium text-gray-700 mb-3">Page Screenshot</h3>
          <img
            src={`/api/screenshots/${encodeURIComponent(screenshotPath.split("/").pop() ?? "")}`}
            alt="Application form screenshot"
            className="w-full rounded-lg border border-gray-100 max-h-96 object-contain bg-gray-50"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
      )}

      {/* Form State Snapshot */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <h3 className="text-sm font-medium text-gray-700 mb-3">Form State</h3>
        {snapshot.external_url && (
          <div className="mb-3">
            <a
              href={snapshot.external_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:text-blue-800 hover:underline break-all"
            >
              {snapshot.external_url}
            </a>
          </div>
        )}
        {fields.length === 0 ? (
          <p className="text-xs text-gray-400">No form fields captured.</p>
        ) : (
          <div className="space-y-3">
            {fields.map((field) => (
              <FormFieldDisplay key={field.field_id} field={field} />
            ))}
          </div>
        )}
      </div>

      {/* Draft Answers (editable for pending, read-only for resolved) */}
      {draftAnswers.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <h3 className="text-sm font-medium text-gray-700 mb-3">
            Draft Answers
            {isPending && (
              <span className="ml-2 text-xs font-normal text-gray-400">
                Edit before submitting
              </span>
            )}
          </h3>
          <div className="space-y-4">
            {draftAnswers.map((draft) => (
              <DraftAnswerField
                key={draft.field_id}
                draft={draft}
                value={editedAnswers[draft.field_id] ?? draft.draft_answer ?? ""}
                readOnly={!isPending}
                onChange={(value) =>
                  setEditedAnswers((prev) => ({ ...prev, [draft.field_id]: value }))
                }
              />
            ))}
          </div>
        </div>
      )}

      {/* Action buttons (only for pending) */}
      {isPending && (
        <div className="flex items-center gap-3">
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="flex-1 px-4 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? "Submitting…" : "Submit"}
          </button>
          <button
            onClick={handleSkip}
            disabled={submitting}
            className="flex-1 px-4 py-2.5 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? "Processing…" : "Skip"}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function BackButton({ onClick }: { onClick: () => void }): React.JSX.Element {
  return (
    <button
      onClick={onClick}
      className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
      aria-label="Back to escalation list"
    >
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
      </svg>
    </button>
  );
}

function TierBadge({ tier }: { tier: string }): React.JSX.Element {
  const isCaptcha = tier === "captcha";
  return (
    <span
      className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
        isCaptcha
          ? "bg-orange-50 text-orange-700"
          : "bg-purple-50 text-purple-700"
      }`}
    >
      {isCaptcha ? "CAPTCHA" : "Review"}
    </span>
  );
}

function StatusBadge({ status }: { status: string }): React.JSX.Element {
  const styles: Record<string, string> = {
    pending: "bg-amber-50 text-amber-700",
    resolved: "bg-green-50 text-green-700",
    auto_submitted: "bg-blue-50 text-blue-700",
    skipped: "bg-gray-100 text-gray-600",
    expired: "bg-red-50 text-red-700",
  };
  return (
    <span
      className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
        styles[status] ?? "bg-gray-100 text-gray-600"
      }`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

function ResolutionBanner({
  status,
  resolutionMethod,
  resolvedAt,
}: {
  status: string;
  resolutionMethod: string | null;
  resolvedAt: string | null;
}): React.JSX.Element {
  const statusLabels: Record<string, string> = {
    resolved: "Submitted by user",
    auto_submitted: "Auto-submitted after timeout",
    skipped: "Skipped by user",
    expired: "Expired",
  };

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 flex items-center gap-3">
      <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center shrink-0">
        <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-700">
          {statusLabels[status] ?? status}
        </p>
        <p className="text-xs text-gray-500">
          {resolutionMethod && <span className="capitalize">{resolutionMethod.replace("_", " ")}</span>}
          {resolvedAt && (
            <span className="ml-2">{formatTimestamp(resolvedAt)}</span>
          )}
        </p>
      </div>
    </div>
  );
}

function FormFieldDisplay({ field }: { field: FormField }): React.JSX.Element {
  return (
    <div className="border-b border-gray-100 pb-2 last:border-0 last:pb-0">
      <label className="block text-xs font-medium text-gray-500 mb-0.5">
        {field.label}
      </label>
      <p className="text-sm text-gray-900">
        {field.value || <span className="text-gray-300 italic">Empty</span>}
      </p>
    </div>
  );
}

function DraftAnswerField({
  draft,
  value,
  readOnly,
  onChange,
}: {
  draft: DraftAnswer;
  value: string;
  readOnly: boolean;
  onChange: (value: string) => void;
}): React.JSX.Element {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {draft.question_text}
      </label>
      {readOnly ? (
        <div className="bg-gray-50 rounded-lg p-3 text-sm text-gray-700 whitespace-pre-wrap">
          {value || <span className="text-gray-300 italic">No answer</span>}
        </div>
      ) : (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={4}
          className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-400 focus:ring-1 focus:ring-blue-400 resize-y"
          placeholder="Edit your answer…"
        />
      )}
    </div>
  );
}

function LoadingSkeleton(): React.JSX.Element {
  return (
    <div className="p-6 space-y-5 animate-pulse">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 bg-gray-200 rounded-lg" />
        <div className="flex-1 space-y-2">
          <div className="h-5 w-48 bg-gray-200 rounded" />
          <div className="h-4 w-32 bg-gray-200 rounded" />
        </div>
      </div>
      <div className="h-48 bg-gray-200 rounded-xl" />
      <div className="h-32 bg-gray-200 rounded-xl" />
      <div className="h-32 bg-gray-200 rounded-xl" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
