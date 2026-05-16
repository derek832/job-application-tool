import { useState, useEffect, useCallback } from "react";
import { getJobs, ApiError } from "../api/client";
import type { JobRecordOut } from "../api/client";

const STATUS_DOT: Record<string, string> = {
  discovered: "bg-gray-400",
  extracted: "bg-blue-400",
  scored: "bg-indigo-400",
  queued: "bg-amber-400",
  approved: "bg-green-400",
  applied: "bg-green-600",
  skipped: "bg-gray-300",
  rejected: "bg-red-400",
  error: "bg-red-600",
};

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "discovered", label: "Discovered" },
  { value: "extracted", label: "Extracted" },
  { value: "scored", label: "Scored" },
  { value: "queued", label: "Queued" },
  { value: "approved", label: "Approved" },
  { value: "applied", label: "Applied" },
  { value: "skipped", label: "Skipped" },
  { value: "rejected", label: "Rejected" },
  { value: "error", label: "Error" },
];

const PAGE_SIZE = 20;

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function JobHistory(): React.JSX.Element {
  const [jobs, setJobs] = useState<JobRecordOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      setError(null);
      const data = await getJobs({
        search: search || undefined,
        status: statusFilter || undefined,
        page,
        limit: PAGE_SIZE,
      });
      setJobs(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter, page]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    fetchJobs();
  }

  return (
    <div className="p-6 space-y-4">
      <h2 className="text-lg font-semibold text-gray-900">Job History</h2>

      {/* Filters */}
      <form onSubmit={handleSearchSubmit} className="flex gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search jobs..."
          className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(1);
          }}
          className="px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </form>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Job list */}
      {loading ? (
        <LoadingSkeleton />
      ) : jobs.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm divide-y divide-gray-100">
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {!loading && jobs.length > 0 && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Previous
          </button>
          <span className="text-xs text-gray-500">Page {page}</span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={jobs.length < PAGE_SIZE}
            className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function JobRow({ job }: { job: JobRecordOut }): React.JSX.Element {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-gray-100 last:border-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center gap-3 hover:bg-gray-50 transition-colors text-left"
      >
        <span
          className={`w-2 h-2 rounded-full shrink-0 ${STATUS_DOT[job.status] ?? "bg-gray-400"}`}
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-900 truncate">{job.job_title}</p>
          <p className="text-xs text-gray-500">{job.company}</p>
        </div>
        {job.fit_score !== null && (
          <span className="text-xs font-medium text-gray-600">{job.fit_score}%</span>
        )}
        <span className="text-xs text-gray-400 shrink-0">
          {formatDate(job.discovered_at)}
        </span>
        <svg
          className={`w-3.5 h-3.5 text-gray-400 shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-3 space-y-2">
          <a
            href={job.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-blue-600 hover:underline"
          >
            View on LinkedIn →
          </a>

          {job.fit_rationale && (
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="text-xs font-medium text-gray-700 mb-1">Scoring Rationale</p>
              <p className="text-xs text-gray-600 leading-relaxed">{job.fit_rationale}</p>
            </div>
          )}

          {job.tailored_resume_text && (
            <TailoringDetails replacementsJson={job.tailored_resume_text} />
          )}

          {job.tailored_resume_pdf && (
            <a
              href={`/api/jobs/${job.id}/pdf`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:underline"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              View Tailored PDF
            </a>
          )}

          {job.application_notes && (
            <ApplicationNotes notesJson={job.application_notes} />
          )}

          <div className="flex items-center gap-3 text-xs text-gray-500">
            <span>Status: <span className="font-medium text-gray-700">{job.status}</span></span>
            {job.queue_reason && (
              <span>Reason: <span className="font-medium text-gray-700">{job.queue_reason}</span></span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function EmptyState(): React.JSX.Element {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-8 text-center shadow-sm">
      <div className="w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center mx-auto mb-3">
        <svg className="w-6 h-6 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75c-2.648 0-5.195-.429-7.577-1.22a2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0" />
        </svg>
      </div>
      <p className="text-sm font-medium text-gray-900">No jobs found</p>
      <p className="text-xs text-gray-500 mt-1">Try adjusting your search or filters.</p>
    </div>
  );
}

function ApplicationNotes({ notesJson }: { notesJson: string }): React.JSX.Element {
  let fields: Array<{ field: string; value: string }> = [];
  try {
    fields = JSON.parse(notesJson);
  } catch {
    return <></>;
  }

  if (!Array.isArray(fields) || fields.length === 0) return <></>;

  return (
    <div className="bg-green-50 rounded-lg p-3">
      <p className="text-xs font-medium text-green-800 mb-2">
        Application Submitted ({fields.length} fields filled)
      </p>
      <div className="space-y-1">
        {fields.map((f, i) => (
          <div key={i} className="text-xs">
            <span className="text-green-700 font-medium">{f.field}:</span>{" "}
            <span className="text-green-900">{f.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TailoringDetails({
  replacementsJson,
}: {
  replacementsJson: string;
}): React.JSX.Element {
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

function LoadingSkeleton(): React.JSX.Element {
  return (
    <div className="space-y-0 animate-pulse bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="px-4 py-3 flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-gray-200" />
          <div className="flex-1 space-y-1">
            <div className="h-3.5 w-3/4 bg-gray-200 rounded" />
            <div className="h-3 w-1/3 bg-gray-200 rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}
