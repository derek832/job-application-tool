import { useState, useEffect } from "react";
import { getUserProfile, updateUserProfile, ApiError } from "../api/client";
import type { UserProfile } from "../api/client";

export function ProfileConfig(): React.JSX.Element {
  const [form, setForm] = useState<UserProfile>({
    full_name: null,
    email: null,
    phone: null,
    location: null,
    work_auth: null,
    linkedin_url: null,
    common_answers: {},
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await getUserProfile();
        setForm(data);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to load profile");
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
      const updated = await updateUserProfile(form);
      setForm(updated);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 2000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  function updateField(field: keyof Omit<UserProfile, "common_answers">, value: string) {
    setForm((prev) => ({ ...prev, [field]: value || null }));
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        <div className="h-5 w-28 bg-gray-200 rounded" />
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="h-12 bg-gray-200 rounded-lg" />
        ))}
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5">
      <h2 className="text-lg font-semibold text-gray-900">Profile</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-4">
        <FormField label="Full Name">
          <input
            type="text"
            value={form.full_name ?? ""}
            onChange={(e) => updateField("full_name", e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <FormField label="Email">
          <input
            type="email"
            value={form.email ?? ""}
            onChange={(e) => updateField("email", e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <FormField label="Phone">
          <input
            type="tel"
            value={form.phone ?? ""}
            onChange={(e) => updateField("phone", e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <FormField label="Location">
          <input
            type="text"
            value={form.location ?? ""}
            onChange={(e) => updateField("location", e.target.value)}
            placeholder="e.g. San Francisco, CA"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <FormField label="Work Authorization">
          <input
            type="text"
            value={form.work_auth ?? ""}
            onChange={(e) => updateField("work_auth", e.target.value)}
            placeholder="e.g. US Citizen, H1B"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <FormField label="LinkedIn URL">
          <input
            type="url"
            value={form.linkedin_url ?? ""}
            onChange={(e) => updateField("linkedin_url", e.target.value)}
            placeholder="https://linkedin.com/in/..."
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        {/* Common Answers key-value editor */}
        <KeyValueEditor
          label="Common Answers"
          pairs={form.common_answers}
          onChange={(pairs) => setForm((f) => ({ ...f, common_answers: pairs }))}
        />

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

interface KeyValueEditorProps {
  label: string;
  pairs: Record<string, string>;
  onChange: (pairs: Record<string, string>) => void;
}

function KeyValueEditor({ label, pairs, onChange }: KeyValueEditorProps): React.JSX.Element {
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");

  function addPair() {
    const key = newKey.trim();
    const value = newValue.trim();
    if (key && value) {
      onChange({ ...pairs, [key]: value });
      setNewKey("");
      setNewValue("");
    }
  }

  function removePair(key: string) {
    const updated = { ...pairs };
    delete updated[key];
    onChange(updated);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      addPair();
    }
  }

  const entries = Object.entries(pairs);

  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1.5">{label}</label>
      <div className="border border-gray-200 rounded-lg bg-white overflow-hidden">
        {entries.length > 0 && (
          <div className="divide-y divide-gray-100">
            {entries.map(([key, value]) => (
              <div key={key} className="flex items-center gap-2 px-3 py-2">
                <span className="text-xs font-medium text-gray-700 min-w-0 truncate">{key}</span>
                <span className="text-xs text-gray-400">→</span>
                <span className="text-xs text-gray-600 flex-1 min-w-0 truncate">{value}</span>
                <button
                  type="button"
                  onClick={() => removePair(key)}
                  className="text-gray-400 hover:text-red-500 shrink-0"
                  aria-label={`Remove ${key}`}
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-2 p-2 border-t border-gray-100">
          <input
            type="text"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Question"
            className="flex-1 px-2 py-1.5 text-xs border border-gray-200 rounded bg-gray-50 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <input
            type="text"
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Answer"
            className="flex-1 px-2 py-1.5 text-xs border border-gray-200 rounded bg-gray-50 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <button
            type="button"
            onClick={addPair}
            className="px-2 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50 rounded transition-colors"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  );
}
