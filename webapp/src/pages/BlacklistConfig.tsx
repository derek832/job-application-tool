import { useState, useEffect, useCallback } from "react";
import {
  getBlacklistConfig,
  addBlacklistCompany,
  removeBlacklistCompany,
  addBlacklistTitle,
  removeBlacklistTitle,
  ApiError,
} from "../api/client";
import type { BlacklistEntry } from "../api/client";

export function BlacklistConfig(): React.JSX.Element {
  const [companies, setCompanies] = useState<BlacklistEntry[]>([]);
  const [titlePatterns, setTitlePatterns] = useState<BlacklistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBlacklist = useCallback(async () => {
    try {
      setError(null);
      const data = await getBlacklistConfig();
      setCompanies(data.companies);
      setTitlePatterns(data.title_patterns);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load blacklist");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBlacklist();
  }, [loadBlacklist]);

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        <div className="h-5 w-48 bg-gray-200 rounded" />
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-12 bg-gray-200 rounded-lg" />
        ))}
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">Blacklist Configuration</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <BlacklistSection
        title="Companies"
        description="Jobs from these companies will be skipped automatically (case-insensitive exact match)."
        entries={companies}
        placeholder="e.g. Revature"
        onAdd={async (value) => {
          await addBlacklistCompany(value);
          await loadBlacklist();
        }}
        onRemove={async (value) => {
          await removeBlacklistCompany(value);
          await loadBlacklist();
        }}
      />

      <BlacklistSection
        title="Title Patterns"
        description="Jobs with titles containing these patterns will be skipped (case-insensitive substring match)."
        entries={titlePatterns}
        placeholder="e.g. intern"
        onAdd={async (value) => {
          await addBlacklistTitle(value);
          await loadBlacklist();
        }}
        onRemove={async (value) => {
          await removeBlacklistTitle(value);
          await loadBlacklist();
        }}
      />
    </div>
  );
}


// ---------------------------------------------------------------------------
// BlacklistSection — reusable section for companies or title patterns
// ---------------------------------------------------------------------------

function BlacklistSection({
  title,
  description,
  entries,
  placeholder,
  onAdd,
  onRemove,
}: {
  title: string;
  description: string;
  entries: BlacklistEntry[];
  placeholder: string;
  onAdd: (value: string) => Promise<void>;
  onRemove: (value: string) => Promise<void>;
}): React.JSX.Element {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sectionError, setSectionError] = useState<string | null>(null);

  async function handleAdd() {
    const value = input.trim();
    if (!value) return;
    if (entries.some((e) => e.value.toLowerCase() === value.toLowerCase())) {
      setSectionError("Entry already exists");
      return;
    }
    setBusy(true);
    setSectionError(null);
    try {
      await onAdd(value);
      setInput("");
    } catch (e) {
      setSectionError(e instanceof ApiError ? e.message : "Failed to add entry");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(value: string) {
    setBusy(true);
    setSectionError(null);
    try {
      await onRemove(value);
    } catch (e) {
      setSectionError(e instanceof ApiError ? e.message : "Failed to remove entry");
    } finally {
      setBusy(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAdd();
    }
  }

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-medium text-gray-800">{title}</h3>
        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
      </div>

      {sectionError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-2 text-xs text-red-700">
          {sectionError}
        </div>
      )}

      {/* Entry list */}
      <div className="space-y-1.5">
        {entries.length === 0 && (
          <p className="text-xs text-gray-400 italic">No entries yet.</p>
        )}
        {entries.map((entry) => (
          <div
            key={entry.value}
            className="flex items-center gap-2 px-3 py-2 bg-white border border-gray-200 rounded-lg"
          >
            <span className="flex-1 text-sm text-gray-800">{entry.value}</span>
            <span
              className="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded-full"
              title={`${entry.hit_count} job${entry.hit_count !== 1 ? "s" : ""} filtered`}
            >
              {entry.hit_count}
            </span>
            <button
              type="button"
              onClick={() => handleRemove(entry.value)}
              disabled={busy}
              className="text-gray-400 hover:text-red-500 text-sm disabled:opacity-50 transition-colors"
              aria-label={`Remove ${entry.value}`}
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {/* Add input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={busy}
          className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
        />
        <button
          type="button"
          onClick={handleAdd}
          disabled={busy || !input.trim()}
          className="px-3 py-2 text-sm font-medium text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {busy ? "..." : "Add"}
        </button>
      </div>
    </div>
  );
}
