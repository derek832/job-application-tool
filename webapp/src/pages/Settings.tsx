import { useState, useEffect } from "react";
import { getSettings, updateSettings, ApiError } from "../api/client";
import type { Settings as SettingsType } from "../api/client";

export function Settings(): React.JSX.Element {
  const [form, setForm] = useState<SettingsType>({
    claude_api_key: null,
    gmail_user: null,
    sms_gateway: null,
    gdocs_script_url: null,
    good_fit_threshold: 70,
    stretch_threshold: 50,
    external_apply_threshold: 80,
    skip_viewed_jobs: true,
    backup_dir: null,
    dry_run: false,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await getSettings();
        setForm(data);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to load settings from server");
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
      // Don't send "***" back for claude_api_key if unchanged
      const payload: Partial<SettingsType> = { ...form };
      if (form.claude_api_key === "***") {
        delete payload.claude_api_key;
      }
      const updated = await updateSettings(payload);
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
        <div className="h-5 w-24 bg-gray-200 rounded" />
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="h-12 bg-gray-200 rounded-lg" />
        ))}
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5">
      <h2 className="text-lg font-semibold text-gray-900">Settings</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Server settings form */}
      <form onSubmit={handleSave} className="space-y-4">
        <FormField label="Claude API Key">
          <input
            type="password"
            value={form.claude_api_key ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, claude_api_key: e.target.value || null }))}
            placeholder="sk-ant-..."
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <FormField label="Gmail User">
          <input
            type="email"
            value={form.gmail_user ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, gmail_user: e.target.value || null }))}
            placeholder="you@gmail.com"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <FormField label="SMS Gateway">
          <input
            type="text"
            value={form.sms_gateway ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, sms_gateway: e.target.value || null }))}
            placeholder="e.g. 5551234567@tmomail.net"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <FormField label="Google Docs Script URL">
          <input
            type="url"
            value={form.gdocs_script_url ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, gdocs_script_url: e.target.value || null }))}
            placeholder="https://script.google.com/..."
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <div className="grid grid-cols-2 gap-3">
          <FormField label="Good Fit Threshold">
            <input
              type="number"
              min={0}
              max={100}
              value={form.good_fit_threshold}
              onChange={(e) =>
                setForm((f) => ({ ...f, good_fit_threshold: parseInt(e.target.value, 10) || 0 }))
              }
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </FormField>
          <FormField label="Stretch Threshold">
            <input
              type="number"
              min={0}
              max={100}
              value={form.stretch_threshold}
              onChange={(e) =>
                setForm((f) => ({ ...f, stretch_threshold: parseInt(e.target.value, 10) || 0 }))
              }
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </FormField>
          <FormField label="External Apply Threshold">
            <input
              type="number"
              min={0}
              max={100}
              value={form.external_apply_threshold}
              onChange={(e) =>
                setForm((f) => ({ ...f, external_apply_threshold: parseInt(e.target.value, 10) || 0 }))
              }
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="text-xs text-gray-400 mt-1">
              Jobs at or above this score auto-submit via Vision Agent. Below this, resume is tailored but you apply manually.
            </p>
          </FormField>
        </div>

        {/* Dry Run toggle */}
        <div className="flex items-center justify-between bg-amber-50 rounded-lg border border-amber-200 px-4 py-3">
          <div>
            <p className="text-sm font-medium text-amber-900">Dry Run Mode</p>
            <p className="text-xs text-amber-700 mt-0.5">
              When enabled, the system simulates actions without submitting applications.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setForm((f) => ({ ...f, dry_run: !f.dry_run }))}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              form.dry_run
                ? "bg-amber-500 text-white"
                : "bg-gray-200 text-gray-700"
            }`}
          >
            {form.dry_run ? "ON" : "OFF"}
          </button>
        </div>

        {/* Skip Viewed Jobs toggle */}
        <div className="flex items-center justify-between bg-white rounded-lg border border-gray-200 px-4 py-3">
          <div>
            <p className="text-sm font-medium text-gray-900">Skip Viewed Jobs</p>
            <p className="text-xs text-gray-500 mt-0.5">
              Skip jobs you've already viewed on LinkedIn during discovery.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setForm((f) => ({ ...f, skip_viewed_jobs: !f.skip_viewed_jobs }))}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              form.skip_viewed_jobs
                ? "bg-blue-600 text-white"
                : "bg-gray-200 text-gray-700"
            }`}
          >
            {form.skip_viewed_jobs ? "ON" : "OFF"}
          </button>
        </div>

        <FormField label="Backup Directory">
          <input
            type="text"
            value={form.backup_dir ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, backup_dir: e.target.value || null }))}
            placeholder="/path/to/backup"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </FormField>

        <button
          type="submit"
          disabled={saving}
          className="w-full px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving..." : success ? "✓ Saved" : "Save Settings"}
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
