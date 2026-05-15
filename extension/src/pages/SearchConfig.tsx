import { useState, useEffect, type FormEvent } from "react";
import {
  getSearchConfig,
  updateSearchConfig,
  type SearchConfig as SearchConfigType,
  ApiError,
} from "../api/client";

type Status = "idle" | "loading" | "saving" | "success" | "error";

const JOB_TYPE_OPTIONS = ["", "full-time", "part-time", "contract", "internship"];
const EXPERIENCE_LEVEL_OPTIONS = ["", "entry", "associate", "mid-senior", "director", "executive"];
const REMOTE_PREF_OPTIONS = ["", "on-site", "remote", "hybrid"];

export function SearchConfig(): React.JSX.Element {
  const [form, setForm] = useState<SearchConfigType>({
    keywords: null,
    location: null,
    job_type: null,
    experience_level: null,
    remote_pref: null,
  });
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    getSearchConfig()
      .then((data) => {
        if (!cancelled) {
          setForm(data);
          setStatus("idle");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setStatus("error");
          setErrorMessage(err instanceof ApiError ? err.detail : "Failed to load search config.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleChange(field: keyof SearchConfigType, value: string): void {
    setForm((prev) => ({ ...prev, [field]: value || null }));
  }

  function handleSubmit(e: FormEvent): void {
    e.preventDefault();
    setStatus("saving");
    setErrorMessage("");
    updateSearchConfig(form)
      .then((saved) => {
        setForm(saved);
        setStatus("success");
      })
      .catch((err: unknown) => {
        setStatus("error");
        setErrorMessage(err instanceof ApiError ? err.detail : "Failed to save search config.");
      });
  }

  if (status === "loading") {
    return <div className="p-4 text-gray-500">Loading search configuration…</div>;
  }

  return (
    <form onSubmit={handleSubmit} className="p-4 space-y-4 max-w-lg">
      <h2 className="text-lg font-semibold text-gray-900">Search Configuration</h2>

      {status === "error" && (
        <div className="rounded bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {errorMessage}
        </div>
      )}
      {status === "success" && (
        <div className="rounded bg-green-50 border border-green-200 p-3 text-sm text-green-700">
          Search configuration saved.
        </div>
      )}

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Keywords</span>
        <input
          type="text"
          value={form.keywords ?? ""}
          onChange={(e) => handleChange("keywords", e.target.value)}
          placeholder="e.g. software engineer, python, react"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Location</span>
        <input
          type="text"
          value={form.location ?? ""}
          onChange={(e) => handleChange("location", e.target.value)}
          placeholder="e.g. San Francisco, CA"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Job Type</span>
        <select
          value={form.job_type ?? ""}
          onChange={(e) => handleChange("job_type", e.target.value)}
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        >
          {JOB_TYPE_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt || "— Any —"}
            </option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Experience Level</span>
        <select
          value={form.experience_level ?? ""}
          onChange={(e) => handleChange("experience_level", e.target.value)}
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        >
          {EXPERIENCE_LEVEL_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt || "— Any —"}
            </option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Remote Preference</span>
        <select
          value={form.remote_pref ?? ""}
          onChange={(e) => handleChange("remote_pref", e.target.value)}
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        >
          {REMOTE_PREF_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt || "— Any —"}
            </option>
          ))}
        </select>
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
