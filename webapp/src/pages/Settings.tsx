import { useState, useEffect, useCallback } from "react";
import { getSettings, updateSettings, getNtfyConfig, updateNtfyConfig, ApiError } from "../api/client";
import type { Settings as SettingsType, NtfyConfigResponse, NtfyConfigUpdate } from "../api/client";

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

function isValidServerUrl(url: string): boolean {
  return /^https?:\/\//.test(url);
}

function isValidLanAddress(address: string): boolean {
  if (!address) return true; // empty is valid (optional field)
  // Strip protocol prefix for host:port validation
  let stripped = address;
  if (stripped.startsWith("http://")) stripped = stripped.slice(7);
  else if (stripped.startsWith("https://")) stripped = stripped.slice(8);
  stripped = stripped.replace(/\/$/, "");
  return /^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[a-zA-Z0-9\-.]+)(:\d{1,5})?$/.test(stripped);
}

// ---------------------------------------------------------------------------
// Settings Page
// ---------------------------------------------------------------------------

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

  const [ntfyConfig, setNtfyConfig] = useState<NtfyConfigResponse>({
    ntfy_enabled: false,
    ntfy_server_url: "https://ntfy.sh",
    urgent_topic: null,
    info_topic: null,
    lan_base_url: null,
  });

  const [ntfyForm, setNtfyForm] = useState<NtfyConfigUpdate>({
    ntfy_enabled: false,
    ntfy_server_url: "https://ntfy.sh",
    lan_base_url: null,
  });

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingNtfy, setSavingNtfy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ntfyError, setNtfyError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [ntfySuccess, setNtfySuccess] = useState(false);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [settingsData, ntfyData] = await Promise.all([
          getSettings(),
          getNtfyConfig(),
        ]);
        setForm(settingsData);
        setNtfyConfig(ntfyData);
        setNtfyForm({
          ntfy_enabled: ntfyData.ntfy_enabled,
          ntfy_server_url: ntfyData.ntfy_server_url,
          lan_base_url: ntfyData.lan_base_url,
        });
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

  async function handleNtfySave(e: React.FormEvent) {
    e.preventDefault();
    setNtfyError(null);
    setNtfySuccess(false);

    // Client-side validation
    if (!isValidServerUrl(ntfyForm.ntfy_server_url)) {
      setNtfyError("Server URL must start with http:// or https://");
      return;
    }
    if (ntfyForm.lan_base_url && !isValidLanAddress(ntfyForm.lan_base_url)) {
      setNtfyError("LAN address must be a valid IPv4 or hostname with optional port (e.g., 192.168.1.100:7432)");
      return;
    }

    setSavingNtfy(true);
    try {
      const updated = await updateNtfyConfig(ntfyForm);
      setNtfyConfig(updated);
      setNtfyForm({
        ntfy_enabled: updated.ntfy_enabled,
        ntfy_server_url: updated.ntfy_server_url,
        lan_base_url: updated.lan_base_url,
      });
      setNtfySuccess(true);
      setTimeout(() => setNtfySuccess(false), 2000);
    } catch (e) {
      setNtfyError(e instanceof ApiError ? e.message : "Failed to save ntfy settings");
    } finally {
      setSavingNtfy(false);
    }
  }

  const copyToClipboard = useCallback((text: string, field: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 1500);
    });
  }, []);

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
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">Settings</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Ntfy Notification Settings */}
      <section className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-gray-900">Push Notifications (ntfy)</h3>
          <span className="text-xs text-gray-400">Primary channel</span>
        </div>

        {ntfyError && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
            {ntfyError}
          </div>
        )}

        <form onSubmit={handleNtfySave} className="space-y-4">
          {/* Ntfy Enabled Toggle */}
          <div className="flex items-center justify-between bg-gray-50 rounded-lg border border-gray-100 px-4 py-3">
            <div>
              <p className="text-sm font-medium text-gray-900">Enable ntfy Notifications</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Push notifications via ntfy.sh to your phone.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setNtfyForm((f: NtfyConfigUpdate) => ({ ...f, ntfy_enabled: !f.ntfy_enabled }))}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                ntfyForm.ntfy_enabled
                  ? "bg-blue-600 text-white"
                  : "bg-gray-200 text-gray-700"
              }`}
            >
              {ntfyForm.ntfy_enabled ? "ON" : "OFF"}
            </button>
          </div>

          {/* Server URL */}
          <FormField label="Ntfy Server URL">
            <input
              type="text"
              value={ntfyForm.ntfy_server_url}
              onChange={(e) => setNtfyForm((f: NtfyConfigUpdate) => ({ ...f, ntfy_server_url: e.target.value }))}
              placeholder="https://ntfy.sh"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="text-xs text-gray-400 mt-1">
              Must start with http:// or https://
            </p>
          </FormField>

          {/* Read-only Topics */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <FormField label="Urgent Topic">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={ntfyConfig.urgent_topic ?? "Not generated yet"}
                  readOnly
                  className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg bg-gray-50 text-gray-600 cursor-default"
                />
                {ntfyConfig.urgent_topic && (
                  <button
                    type="button"
                    onClick={() => copyToClipboard(ntfyConfig.urgent_topic!, "urgent")}
                    className="px-2.5 py-2 text-xs font-medium text-gray-600 bg-gray-100 border border-gray-200 rounded-lg hover:bg-gray-200 transition-colors"
                    title="Copy to clipboard"
                  >
                    {copiedField === "urgent" ? "✓" : "Copy"}
                  </button>
                )}
              </div>
              <p className="text-xs text-gray-400 mt-1">
                Subscribe to this topic in the ntfy app for urgent alerts.
              </p>
            </FormField>

            <FormField label="Info Topic">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={ntfyConfig.info_topic ?? "Not generated yet"}
                  readOnly
                  className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg bg-gray-50 text-gray-600 cursor-default"
                />
                {ntfyConfig.info_topic && (
                  <button
                    type="button"
                    onClick={() => copyToClipboard(ntfyConfig.info_topic!, "info")}
                    className="px-2.5 py-2 text-xs font-medium text-gray-600 bg-gray-100 border border-gray-200 rounded-lg hover:bg-gray-200 transition-colors"
                    title="Copy to clipboard"
                  >
                    {copiedField === "info" ? "✓" : "Copy"}
                  </button>
                )}
              </div>
              <p className="text-xs text-gray-400 mt-1">
                Subscribe to this topic for run summaries.
              </p>
            </FormField>
          </div>

          {/* LAN IP/Hostname */}
          <FormField label="LAN IP / Hostname">
            <input
              type="text"
              value={ntfyForm.lan_base_url ?? ""}
              onChange={(e) => setNtfyForm((f: NtfyConfigUpdate) => ({ ...f, lan_base_url: e.target.value || null }))}
              placeholder="e.g., 192.168.1.100:7432"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="text-xs text-gray-400 mt-1">
              Required for approve/reject action buttons on notifications. Leave empty to disable.
            </p>
          </FormField>

          <button
            type="submit"
            disabled={savingNtfy}
            className="w-full px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {savingNtfy ? "Saving..." : ntfySuccess ? "✓ Saved" : "Save Ntfy Settings"}
          </button>
        </form>
      </section>

      {/* General Settings (existing form) */}
      <section className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
        <h3 className="text-sm font-semibold text-gray-900">General Settings</h3>

        <form onSubmit={handleSave} className="space-y-4">
          <FormField label="Claude API Key">
            <input
              type="password"
              value={form.claude_api_key ?? ""}
              onChange={(e) => setForm((f: SettingsType) => ({ ...f, claude_api_key: e.target.value || null }))}
              placeholder="sk-ant-..."
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </FormField>

          <FormField label="Gmail User">
            <input
              type="email"
              value={form.gmail_user ?? ""}
              onChange={(e) => setForm((f: SettingsType) => ({ ...f, gmail_user: e.target.value || null }))}
              placeholder="you@gmail.com"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </FormField>

          <FormField label="SMS Gateway">
            <input
              type="text"
              value={form.sms_gateway ?? ""}
              onChange={(e) => setForm((f: SettingsType) => ({ ...f, sms_gateway: e.target.value || null }))}
              placeholder="e.g. 5551234567@tmomail.net"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="text-xs text-gray-400 mt-1">
              Fallback channel when ntfy is unavailable.
            </p>
          </FormField>

          <FormField label="Google Docs Script URL">
            <input
              type="url"
              value={form.gdocs_script_url ?? ""}
              onChange={(e) => setForm((f: SettingsType) => ({ ...f, gdocs_script_url: e.target.value || null }))}
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
                  setForm((f: SettingsType) => ({ ...f, good_fit_threshold: parseInt(e.target.value, 10) || 0 }))
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
                  setForm((f: SettingsType) => ({ ...f, stretch_threshold: parseInt(e.target.value, 10) || 0 }))
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
                  setForm((f: SettingsType) => ({ ...f, external_apply_threshold: parseInt(e.target.value, 10) || 0 }))
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
              onClick={() => setForm((f: SettingsType) => ({ ...f, dry_run: !f.dry_run }))}
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
              onClick={() => setForm((f: SettingsType) => ({ ...f, skip_viewed_jobs: !f.skip_viewed_jobs }))}
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
              onChange={(e) => setForm((f: SettingsType) => ({ ...f, backup_dir: e.target.value || null }))}
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
      </section>
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
