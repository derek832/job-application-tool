import { useState, useEffect, type FormEvent } from "react";
import {
  getGoalsProfile,
  updateGoalsProfile,
  type GoalsProfile as GoalsProfileType,
  ApiError,
} from "../api/client";

type Status = "idle" | "loading" | "saving" | "success" | "error";

/**
 * Converts a comma-separated string to a trimmed string array,
 * filtering out empty entries.
 */
function csvToList(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/**
 * Converts a string array to a comma-separated display string.
 */
function listToCsv(items: string[]): string {
  return items.join(", ");
}

export function GoalsProfile(): React.JSX.Element {
  const [form, setForm] = useState<GoalsProfileType>({
    target_titles: [],
    industries: [],
    company_sizes: [],
    geo_prefs: [],
    min_salary: null,
    deal_breakers: [],
    open_to_stretch: true,
    career_objective: null,
  });
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    getGoalsProfile()
      .then((data) => {
        if (!cancelled) {
          setForm(data);
          setStatus("idle");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setStatus("error");
          setErrorMessage(err instanceof ApiError ? err.detail : "Failed to load goals profile.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleListChange(field: keyof GoalsProfileType, value: string): void {
    setForm((prev) => ({ ...prev, [field]: csvToList(value) }));
  }

  function handleSubmit(e: FormEvent): void {
    e.preventDefault();
    setStatus("saving");
    setErrorMessage("");
    updateGoalsProfile(form)
      .then((saved) => {
        setForm(saved);
        setStatus("success");
      })
      .catch((err: unknown) => {
        setStatus("error");
        setErrorMessage(err instanceof ApiError ? err.detail : "Failed to save goals profile.");
      });
  }

  if (status === "loading") {
    return <div className="p-4 text-gray-500">Loading goals profile…</div>;
  }

  return (
    <form onSubmit={handleSubmit} className="p-4 space-y-4 max-w-lg">
      <h2 className="text-lg font-semibold text-gray-900">Goals Profile</h2>

      {status === "error" && (
        <div className="rounded bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {errorMessage}
        </div>
      )}
      {status === "success" && (
        <div className="rounded bg-green-50 border border-green-200 p-3 text-sm text-green-700">
          Goals profile saved.
        </div>
      )}

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Target Titles</span>
        <input
          type="text"
          value={listToCsv(form.target_titles)}
          onChange={(e) => handleListChange("target_titles", e.target.value)}
          placeholder="e.g. Software Engineer, Backend Developer"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
        <span className="text-xs text-gray-500">Comma-separated list</span>
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Industries</span>
        <input
          type="text"
          value={listToCsv(form.industries)}
          onChange={(e) => handleListChange("industries", e.target.value)}
          placeholder="e.g. Technology, Finance, Healthcare"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
        <span className="text-xs text-gray-500">Comma-separated list</span>
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Company Sizes</span>
        <input
          type="text"
          value={listToCsv(form.company_sizes)}
          onChange={(e) => handleListChange("company_sizes", e.target.value)}
          placeholder="e.g. Startup, Mid-size, Enterprise"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
        <span className="text-xs text-gray-500">Comma-separated list</span>
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Geographic Preferences</span>
        <input
          type="text"
          value={listToCsv(form.geo_prefs)}
          onChange={(e) => handleListChange("geo_prefs", e.target.value)}
          placeholder="e.g. San Francisco, New York, Remote"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
        <span className="text-xs text-gray-500">Comma-separated list</span>
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Minimum Salary</span>
        <input
          type="number"
          value={form.min_salary ?? ""}
          onChange={(e) =>
            setForm((prev) => ({
              ...prev,
              min_salary: e.target.value ? parseInt(e.target.value, 10) : null,
            }))
          }
          placeholder="e.g. 120000"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Deal Breakers</span>
        <input
          type="text"
          value={listToCsv(form.deal_breakers)}
          onChange={(e) => handleListChange("deal_breakers", e.target.value)}
          placeholder="e.g. clearance required, unpaid, relocation mandatory"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
        <span className="text-xs text-gray-500">Comma-separated list</span>
      </label>

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={form.open_to_stretch}
          onChange={(e) => setForm((prev) => ({ ...prev, open_to_stretch: e.target.checked }))}
          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        />
        <span className="text-sm font-medium text-gray-700">Open to stretch roles</span>
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Career Objective</span>
        <textarea
          value={form.career_objective ?? ""}
          onChange={(e) =>
            setForm((prev) => ({ ...prev, career_objective: e.target.value || null }))
          }
          placeholder="Describe your career goals and what you're looking for…"
          rows={4}
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
      </label>

      <button
        type="submit"
        disabled={status === "saving"}
        className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {status === "saving" ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
