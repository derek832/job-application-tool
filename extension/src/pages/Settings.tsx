import { useState, useEffect, type FormEvent } from "react";
import {
  getSettings,
  updateSettings,
  type Settings as SettingsType,
  ApiError,
} from "../api/client";

type Status = "idle" | "loading" | "saving" | "success" | "error";

/** Fields that contain secrets and must render as password inputs. */
const SECRET_FIELDS: ReadonlySet<keyof SettingsType> = new Set([
  "claude_api_key",
]);

export function Settings(): React.JSX.Element {
  const [form, setForm] = useState<SettingsType>({
    claude_api_key: null,
    gmail_user: null,
    sms_gateway: null,
    gdocs_script_url: null,
    scheduled_time: null,
    good_fit_threshold: 75,
    stretch_threshold: 50,
    backup_dir: null,
    dry_run: true,
  });
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    getSettings()
      .then((data) => {
        if (!cancelled) {
          setForm(data);
          setStatus("idle");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setStatus("error");
          setErrorMessage(err instanceof ApiError ? err.detail : "Failed to load settings.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleStringChange(field: keyof SettingsType, value: string): void {
    setForm((prev) => ({ ...prev, [field]: value || null }));
  }

  function handleIntChange(field: keyof SettingsType, value: string): void {
    const parsed = parseInt(value, 10);
    setForm((prev) => ({ ...prev, [field]: isNaN(parsed) ? 0 : parsed }));
  }

  function handleSubmit(e: FormEvent): void {
    e.preventDefault();
    setStatus("saving");
    setErrorMessage("");

    // Build partial payload: only include secret fields if user changed them from the redacted value
    const payload: Partial<SettingsType> = { ...form };

    // If a secret field still shows the redacted placeholder, exclude it from the update
    for (const field of SECRET_FIELDS) {
      if (payload[field] === "***") {
        delete payload[field];
      }
    }

    updateSettings(payload)
      .then((saved) => {
        setForm(saved);
        setStatus("success");
      })
      .catch((err: unknown) => {
        setStatus("error");
        setErrorMessage(err instanceof ApiError ? err.detail : "Failed to save settings.");
      });
  }

  if (status === "loading") {
    return <div className="p-4 text-gray-500">Loading settings…</div>;
  }

  return (
    <form onSubmit={handleSubmit} className="p-4 space-y-4 max-w-lg">
      <h2 className="text-lg font-semibold text-gray-900">Settings</h2>

      {status === "error" && (
        <div className="rounded bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {errorMessage}
        </div>
      )}
      {status === "success" && (
        <div className="rounded bg-green-50 border border-green-200 p-3 text-sm text-green-700">
          Settings saved.
        </div>
      )}

      {/* Secret fields */}
      <fieldset className="space-y-4">
        <legend className="text-sm font-semibold text-gray-800">Credentials</legend>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Claude API Key</span>
          <input
            type="password"
            value={form.claude_api_key ?? ""}
            onChange={(e) => handleStringChange("claude_api_key", e.target.value)}
            placeholder="sk-ant-…"
            autoComplete="off"
            className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Gmail User</span>
          <input
            type="email"
            value={form.gmail_user ?? ""}
            onChange={(e) => handleStringChange("gmail_user", e.target.value)}
            placeholder="your-email@domain.com"
            autoComplete="off"
            className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
          <span className="text-xs text-gray-500">Gmail/Workspace account (OAuth2 auth — no password needed)</span>
        </label>
      </fieldset>

      {/* Non-secret fields */}
      <fieldset className="space-y-4">
        <legend className="text-sm font-semibold text-gray-800">Notifications & Integration</legend>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">SMS Gateway</span>
          <input
            type="text"
            value={form.sms_gateway ?? ""}
            onChange={(e) => handleStringChange("sms_gateway", e.target.value)}
            placeholder="e.g. 5307558669@vtext.com"
            className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Google Docs Script URL</span>
          <input
            type="url"
            value={form.gdocs_script_url ?? ""}
            onChange={(e) => handleStringChange("gdocs_script_url", e.target.value)}
            placeholder="https://script.google.com/macros/s/…/exec"
            className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </label>
      </fieldset>

      <fieldset className="space-y-4">
        <legend className="text-sm font-semibold text-gray-800">Schedule & Thresholds</legend>

        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={form.dry_run}
            onChange={(e) => setForm((prev) => ({ ...prev, dry_run: e.target.checked }))}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm font-medium text-gray-700">Dry Run Mode</span>
        </label>
        <span className="block text-xs text-gray-500 -mt-2 ml-7">
          Runs the full pipeline (search, score, tailor) but skips actual application submission. Turn off when ready to apply for real.
        </span>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Scheduled Time</span>
          <input
            type="time"
            value={form.scheduled_time ?? ""}
            onChange={(e) => handleStringChange("scheduled_time", e.target.value)}
            className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Good Fit Threshold</span>
          <input
            type="number"
            min={0}
            max={100}
            value={form.good_fit_threshold}
            onChange={(e) => handleIntChange("good_fit_threshold", e.target.value)}
            className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
          <span className="text-xs text-gray-500">Score at or above this is auto-approved (default: 75)</span>
        </label>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Stretch Threshold</span>
          <input
            type="number"
            min={0}
            max={100}
            value={form.stretch_threshold}
            onChange={(e) => handleIntChange("stretch_threshold", e.target.value)}
            className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
          <span className="text-xs text-gray-500">Score between this and good-fit goes to human queue (default: 50)</span>
        </label>
      </fieldset>

      <fieldset className="space-y-4">
        <legend className="text-sm font-semibold text-gray-800">Storage</legend>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Backup Directory</span>
          <input
            type="text"
            value={form.backup_dir ?? ""}
            onChange={(e) => handleStringChange("backup_dir", e.target.value)}
            placeholder="/path/to/backup"
            className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </label>
      </fieldset>

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
