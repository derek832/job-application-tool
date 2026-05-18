import { useState, useEffect } from "react";
import { getSearchConfig, updateSearchConfig, ApiError } from "../api/client";
import type { SearchConfig as SearchConfigType } from "../api/client";

const JOB_TYPES = [
  { value: "", label: "Any" },
  { value: "full-time", label: "Full-time" },
  { value: "part-time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "internship", label: "Internship" },
];

const EXPERIENCE_LEVELS = [
  { value: "", label: "Any" },
  { value: "entry", label: "Entry Level" },
  { value: "associate", label: "Associate" },
  { value: "mid-senior", label: "Mid-Senior" },
  { value: "director", label: "Director" },
  { value: "executive", label: "Executive" },
];

const REMOTE_PREFS = [
  { value: "", label: "Any" },
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "on-site", label: "On-site" },
];

const TIME_RANGES = [
  { value: "1", label: "1 day" },
  { value: "2", label: "2 days" },
  { value: "3", label: "3 days" },
  { value: "5", label: "5 days" },
  { value: "7", label: "7 days" },
  { value: "14", label: "14 days" },
  { value: "30", label: "30 days" },
  { value: "0", label: "Any time" },
];

const SORT_OPTIONS = [
  { value: "recent", label: "Most recent" },
  { value: "relevant", label: "Most relevant" },
];

export function SearchConfig(): React.JSX.Element {
  const [form, setForm] = useState<SearchConfigType>({
    keywords: null,
    search_queries: [],
    location: null,
    job_type: null,
    experience_level: null,
    remote_pref: null,
    time_range: "2",
    sort_by: "recent",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await getSearchConfig();
        setForm(data);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to load config");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const updated = await updateSearchConfig(form);
      setForm(updated);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 2000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  function updateField(field: keyof Omit<SearchConfigType, "search_queries">, value: string) {
    setForm((prev) => ({ ...prev, [field]: value || null }));
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        <div className="h-5 w-36 bg-gray-200 rounded" />
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-12 bg-gray-200 rounded-lg" />
        ))}
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5">
      <h2 className="text-lg font-semibold text-gray-900">Search Config</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            Search Queries
            <span className="ml-1 text-gray-400 font-normal">(max 10)</span>
          </label>
          <p className="text-xs text-gray-400 mb-2">
            Each query runs as a separate LinkedIn search. All share the same filters below.
          </p>
          <SearchQueryList
            queries={form.search_queries}
            onChange={(queries) => setForm((f) => ({ ...f, search_queries: queries }))}
          />
        </div>

        <FormField label="Location">
          <input
            type="text"
            value={form.location ?? ""}
            onChange={(e) => updateField("location", e.target.value)}
            placeholder="e.g. San Francisco, CA"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <FormField label="Job Type">
          <select
            value={form.job_type ?? ""}
            onChange={(e) => updateField("job_type", e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {JOB_TYPES.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </FormField>

        <FormField label="Experience Level">
          <select
            value={form.experience_level ?? ""}
            onChange={(e) => updateField("experience_level", e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {EXPERIENCE_LEVELS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </FormField>

        <FormField label="Remote Preference">
          <select
            value={form.remote_pref ?? ""}
            onChange={(e) => updateField("remote_pref", e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {REMOTE_PREFS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </FormField>

        <FormField label="Time Range">
          <select
            value={form.time_range ?? "24h"}
            onChange={(e) => updateField("time_range", e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {TIME_RANGES.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </FormField>

        <FormField label="Sort By">
          <select
            value={form.sort_by ?? "recent"}
            onChange={(e) => updateField("sort_by", e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </FormField>

        <button
          type="submit"
          disabled={saving}
          className="w-full px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving..." : success ? "✓ Saved" : "Save Changes"}
        </button>
      </form>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1.5">{label}</label>
      {children}
    </div>
  );
}

const MAX_QUERIES = 10;

function SearchQueryList({
  queries,
  onChange,
}: {
  queries: string[];
  onChange: (queries: string[]) => void;
}): React.JSX.Element {
  const [input, setInput] = useState("");

  function addQuery() {
    const value = input.trim();
    if (value && !queries.includes(value) && queries.length < MAX_QUERIES) {
      onChange([...queries, value]);
      setInput("");
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      addQuery();
    }
  }

  function removeQuery(index: number) {
    onChange(queries.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-2">
      <div className="space-y-1.5">
        {queries.map((query, i) => (
          <div
            key={`${query}-${i}`}
            className="flex items-center gap-2 px-3 py-1.5 bg-white border border-gray-200 rounded-lg"
          >
            <span className="flex-1 text-sm text-gray-800">{query}</span>
            <button
              type="button"
              onClick={() => removeQuery(i)}
              className="text-gray-400 hover:text-red-500 text-sm"
              aria-label={`Remove query: ${query}`}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      {queries.length < MAX_QUERIES && (
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="e.g. security engineer NOT devsecops"
            className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          <button
            type="button"
            onClick={addQuery}
            disabled={!input.trim()}
            className="px-3 py-2 text-sm font-medium text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Add
          </button>
        </div>
      )}
      {queries.length >= MAX_QUERIES && (
        <p className="text-xs text-amber-600">Maximum of {MAX_QUERIES} queries reached.</p>
      )}
    </div>
  );
}
