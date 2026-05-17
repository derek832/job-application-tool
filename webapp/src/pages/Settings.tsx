import { useState, useEffect, useRef, useCallback } from "react";
import { getSettings, updateSettings, detectLanIp, ApiError } from "../api/client";
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

  // LAN IP detection state
  const [lanIp, setLanIp] = useState("");
  const [detectLoading, setDetectLoading] = useState(false);
  const [detectError, setDetectError] = useState<string | null>(null);
  const detectErrorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearDetectError = useCallback(() => {
    setDetectError(null);
    if (detectErrorTimerRef.current) {
      clearTimeout(detectErrorTimerRef.current);
      detectErrorTimerRef.current = null;
    }
  }, []);

  async function handleDetectLanIp() {
    clearDetectError();
    setDetectLoading(true);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10_000);

    try {
      const result = await detectLanIp(controller.signal);
      setLanIp(result.lan_base_url);
    } catch (e) {
      let message: string;
      if (e instanceof DOMException && e.name === "AbortError") {
        message = "Detection timed out. Please try again or enter your LAN IP manually.";
      } else if (e instanceof ApiError) {
        message = e.detail || e.message;
      } else {
        message = "Detection failed. Please try again or enter your LAN IP manually.";
      }
      setDetectError(message);
      detectErrorTimerRef.current = setTimeout(() => {
        setDetectError(null);
        detectErrorTimerRef.current = null;
      }, 8_000);
    } finally {
      clearTimeout(timeoutId);
      setDetectLoading(false);
    }
  }

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

  // Cleanup detect error timer on unmount
  useEffect(() => {
    return () => {
      if (detectErrorTimerRef.current) {
        clearTimeout(detectErrorTimerRef.current);
      }
    };
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

      {/* Ntfy Configuration Section */}
      <div className="border-t border-gray-200 pt-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Ntfy Notification Settings</h3>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            LAN IP / Hostname
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={lanIp}
              onChange={(e) => setLanIp(e.target.value)}
              placeholder="e.g., http://192.168.1.100:7432"
              className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <button
              type="button"
              onClick={handleDetectLanIp}
              disabled={detectLoading}
              className="px-3 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors inline-flex items-center gap-1.5"
            >
              {detectLoading && (
                <svg
                  className="animate-spin h-4 w-4"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
              )}
              Detect
            </button>
          </div>
          {detectError && (
            <p className="mt-1.5 text-xs text-red-600">{detectError}</p>
          )}
          <p className="text-xs text-gray-400 mt-1">
            Base URL for ntfy action buttons to reach the automator over LAN.
          </p>
        </div>
      </div>
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
