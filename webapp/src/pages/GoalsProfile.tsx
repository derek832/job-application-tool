import { useState, useEffect } from "react";
import { getGoalsProfile, updateGoalsProfile, ApiError } from "../api/client";
import type { GoalsProfile as GoalsProfileType } from "../api/client";

export function GoalsProfile(): React.JSX.Element {
  const [form, setForm] = useState<GoalsProfileType>({
    target_titles: [],
    industries: [],
    company_sizes: [],
    geo_prefs: [],
    min_salary: null,
    deal_breakers: [],
    open_to_stretch: false,
    career_objective: null,
    supplementary_context: null,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await getGoalsProfile();
        setForm(data);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to load goals");
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
      const updated = await updateGoalsProfile(form);
      setForm(updated);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 2000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        <div className="h-5 w-32 bg-gray-200 rounded" />
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-16 bg-gray-200 rounded-lg" />
        ))}
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5">
      <h2 className="text-lg font-semibold text-gray-900">Career Goals</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-4">
        <TagInput
          label="Target Titles"
          tags={form.target_titles}
          onChange={(tags) => setForm((f) => ({ ...f, target_titles: tags }))}
          placeholder="Add a title..."
        />

        <TagInput
          label="Industries"
          tags={form.industries}
          onChange={(tags) => setForm((f) => ({ ...f, industries: tags }))}
          placeholder="Add an industry..."
        />

        <TagInput
          label="Company Sizes"
          tags={form.company_sizes}
          onChange={(tags) => setForm((f) => ({ ...f, company_sizes: tags }))}
          placeholder="e.g. startup, mid-size..."
        />

        <TagInput
          label="Location Preferences"
          tags={form.geo_prefs}
          onChange={(tags) => setForm((f) => ({ ...f, geo_prefs: tags }))}
          placeholder="Add a location..."
        />

        <TagInput
          label="Deal Breakers"
          tags={form.deal_breakers}
          onChange={(tags) => setForm((f) => ({ ...f, deal_breakers: tags }))}
          placeholder="Add a deal breaker..."
        />

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            Minimum Salary
          </label>
          <input
            type="number"
            value={form.min_salary ?? ""}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                min_salary: e.target.value ? parseInt(e.target.value, 10) : null,
              }))
            }
            placeholder="e.g. 120000"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        <div className="flex items-center justify-between bg-white rounded-lg border border-gray-200 px-3 py-2.5">
          <div>
            <p className="text-sm font-medium text-gray-900">Open to Stretch Roles</p>
            <p className="text-xs text-gray-500">Consider roles slightly outside your criteria</p>
          </div>
          <button
            type="button"
            onClick={() => setForm((f) => ({ ...f, open_to_stretch: !f.open_to_stretch }))}
            className={`relative w-9 h-5 rounded-full transition-colors ${
              form.open_to_stretch ? "bg-blue-600" : "bg-gray-300"
            }`}
            role="switch"
            aria-checked={form.open_to_stretch}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                form.open_to_stretch ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            Career Objective
          </label>
          <textarea
            value={form.career_objective ?? ""}
            onChange={(e) =>
              setForm((f) => ({ ...f, career_objective: e.target.value || null }))
            }
            rows={3}
            placeholder="Describe your career goals..."
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            Supplementary Context
          </label>
          <p className="text-xs text-gray-400 mb-1">
            Additional experience notes, project details, or work context. Passed to Claude for
            better scoring and keyword matching but not included in the exported resume PDF.
          </p>
          <textarea
            value={form.supplementary_context ?? ""}
            onChange={(e) =>
              setForm((f) => ({ ...f, supplementary_context: e.target.value || null }))
            }
            rows={6}
            placeholder="Paste detailed work notes, project descriptions, certifications, or other context that helps Claude match you to jobs..."
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-y"
          />
        </div>

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

interface TagInputProps {
  label: string;
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder: string;
}

function TagInput({ label, tags, onChange, placeholder }: TagInputProps): React.JSX.Element {
  const [input, setInput] = useState("");

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const value = input.trim();
      if (value && !tags.includes(value)) {
        onChange([...tags, value]);
      }
      setInput("");
    } else if (e.key === "Backspace" && input === "" && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  }

  function removeTag(index: number) {
    onChange(tags.filter((_, i) => i !== index));
  }

  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1.5">{label}</label>
      <div className="flex flex-wrap gap-1.5 p-2 border border-gray-200 rounded-lg bg-white min-h-[38px]">
        {tags.map((tag, i) => (
          <span
            key={`${tag}-${i}`}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-blue-50 text-blue-700"
          >
            {tag}
            <button
              type="button"
              onClick={() => removeTag(i)}
              className="text-blue-400 hover:text-blue-600"
              aria-label={`Remove ${tag}`}
            >
              ×
            </button>
          </span>
        ))}
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={tags.length === 0 ? placeholder : ""}
          className="flex-1 min-w-[80px] text-sm outline-none bg-transparent"
        />
      </div>
    </div>
  );
}
