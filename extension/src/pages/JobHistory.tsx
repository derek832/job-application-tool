import { useCallback, useEffect, useState } from "react";
import { getJobs, type GetJobsParams, type JobRecordOut } from "../api/client";

const VALID_STATUSES = [
  "discovered",
  "extracted",
  "extraction_failed",
  "scored",
  "approved_for_apply",
  "skipped",
  "rejected_by_user",
  "resume_failed",
  "applying",
  "apply_failed",
  "applied",
  "manually_applied",
] as const;

const STATUS_COLORS: Record<string, string> = {
  discovered: "bg-gray-100 text-gray-700",
  extracted: "bg-blue-100 text-blue-700",
  extraction_failed: "bg-red-100 text-red-700",
  scored: "bg-indigo-100 text-indigo-700",
  approved_for_apply: "bg-green-100 text-green-700",
  skipped: "bg-yellow-100 text-yellow-700",
  rejected_by_user: "bg-orange-100 text-orange-700",
  resume_failed: "bg-red-100 text-red-700",
  applying: "bg-cyan-100 text-cyan-700",
  apply_failed: "bg-red-100 text-red-700",
  applied: "bg-emerald-100 text-emerald-700",
  manually_applied: "bg-teal-100 text-teal-700",
};

const PAGE_SIZE = 20;

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function JobHistory() {
  const [jobs, setJobs] = useState<JobRecordOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: GetJobsParams = {
        page,
        limit: PAGE_SIZE,
      };
      if (search.trim()) {
        params.search = search.trim();
      }
      if (statusFilter) {
        params.status = statusFilter;
      }
      const data = await getJobs(params);
      setJobs(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load jobs";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [page, search, statusFilter]);

  useEffect(() => {
    void fetchJobs();
  }, [fetchJobs]);

  function handleSearchChange(e: React.ChangeEvent<HTMLInputElement>) {
    setSearch(e.target.value);
    setPage(1);
  }

  function handleStatusChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setStatusFilter(e.target.value);
    setPage(1);
  }

  function handlePrevPage() {
    setPage((p) => Math.max(1, p - 1));
  }

  function handleNextPage() {
    setPage((p) => p + 1);
  }

  return (
    <div className="p-4 space-y-4">
      <h1 className="text-xl font-semibold text-gray-900">Job History</h1>

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <input
          type="text"
          placeholder="Search by title or company..."
          value={search}
          onChange={handleSearchChange}
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <select
          value={statusFilter}
          onChange={handleStatusChange}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          <option value="">All statuses</option>
          {VALID_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>

      {/* Error state */}
      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="text-center text-sm text-gray-500 py-8">
          Loading jobs...
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && jobs.length === 0 && (
        <div className="text-center text-sm text-gray-500 py-8">
          No jobs found.
        </div>
      )}

      {/* Table */}
      {!loading && jobs.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Title
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Company
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Status
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Fit Score
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Discovered
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Applied
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {jobs.map((job) => (
                <tr key={job.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900 max-w-[200px] truncate">
                    <a
                      href={job.linkedin_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:text-blue-600 hover:underline"
                      title={job.job_title}
                    >
                      {job.job_title}
                    </a>
                  </td>
                  <td className="px-4 py-3 text-gray-700 max-w-[150px] truncate">
                    {job.company}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[job.status] ?? "bg-gray-100 text-gray-700"}`}
                    >
                      {job.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-700">
                    {job.fit_score !== null ? job.fit_score : "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                    {formatTimestamp(job.discovered_at)}
                  </td>
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                    {formatTimestamp(job.applied_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {!loading && jobs.length > 0 && (
        <div className="flex items-center justify-between pt-2">
          <button
            onClick={handlePrevPage}
            disabled={page <= 1}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-sm text-gray-600">Page {page}</span>
          <button
            onClick={handleNextPage}
            disabled={jobs.length < PAGE_SIZE}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
