import { useState, useEffect, useRef, useCallback } from "react";
import { getSettings, updateSettings, getNtfyConfig, updateNtfyConfig, detectLanIp, getScheduleConfig, updateScheduleConfig, getScheduleNext, testNtfyConnection, getNtfyTestStatus, ApiError } from "../api/client";
import type { Settings as SettingsType, NtfyConfigResponse, NtfyConfigUpdate, ScheduleConfigUpdate } from "../api/client";

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
    human_review_threshold: 85,
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

  // LAN IP detection state
  const [detectLoading, setDetectLoading] = useState(false);
  const [detectError, setDetectError] = useState<string | null>(null);
  const detectErrorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Ntfy connection test state
  const [ntfyTesting, setNtfyTesting] = useState(false);
  const [ntfyTestResult, setNtfyTestResult] = useState<"idle" | "sent" | "confirmed" | "failed">("idle");
  const [ntfyTestError, setNtfyTestError] = useState<string | null>(null);
  const ntfyTestPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Schedule configuration state
  const [scheduleForm, setScheduleForm] = useState<ScheduleConfigUpdate>({
    mode: "specific_times",
    times: ["09:00", "13:00", "17:00"],
    interval_hours: 2,
    window_start: "08:00",
    window_end: "20:00",
    weekend_runs: false,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    quiet_hours_start: null,
    quiet_hours_end: null,
  });
  const [scheduleLoading, setScheduleLoading] = useState(true);
  const [scheduleSaving, setScheduleSaving] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [scheduleSuccess, setScheduleSuccess] = useState(false);
  const [scheduleValidationError, setScheduleValidationError] = useState<string | null>(null);
  const [nextRuns, setNextRuns] = useState<string[]>([]);
  const [nextRunsLoading, setNextRunsLoading] = useState(false);

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
      setNtfyForm((f: NtfyConfigUpdate) => ({ ...f, lan_base_url: result.lan_base_url }));
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

  async function handleNtfyTest() {
    // Clear previous state
    setNtfyTesting(true);
    setNtfyTestResult("idle");
    setNtfyTestError(null);
    if (ntfyTestPollRef.current) {
      clearInterval(ntfyTestPollRef.current);
      ntfyTestPollRef.current = null;
    }

    try {
      const result = await testNtfyConnection();
      if (result.sent) {
        setNtfyTestResult("sent");
        // Start polling for confirmation
        ntfyTestPollRef.current = setInterval(async () => {
          try {
            const status = await getNtfyTestStatus();
            if (status.confirmed) {
              setNtfyTestResult("confirmed");
              if (ntfyTestPollRef.current) {
                clearInterval(ntfyTestPollRef.current);
                ntfyTestPollRef.current = null;
              }
              setNtfyTesting(false);
            }
          } catch {
            // Silently continue polling
          }
        }, 2000);
        // Stop polling after 60 seconds
        setTimeout(() => {
          if (ntfyTestPollRef.current) {
            clearInterval(ntfyTestPollRef.current);
            ntfyTestPollRef.current = null;
          }
          setNtfyTesting(false);
        }, 60_000);
      } else {
        setNtfyTestResult("failed");
        setNtfyTestError(result.error ?? "Unknown error");
        setNtfyTesting(false);
      }
    } catch (e) {
      setNtfyTestResult("failed");
      setNtfyTestError(e instanceof ApiError ? (e.detail || e.message) : "Failed to send test");
      setNtfyTesting(false);
    }
  }

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

  // Load schedule config separately (non-blocking)
  useEffect(() => {
    async function loadSchedule() {
      try {
        const [scheduleData, nextData] = await Promise.all([
          getScheduleConfig(),
          getScheduleNext().catch(() => ({ next_runs: [] })),
        ]);
        setScheduleForm({
          mode: scheduleData.mode,
          times: scheduleData.times,
          interval_hours: scheduleData.interval_hours,
          window_start: scheduleData.window_start,
          window_end: scheduleData.window_end,
          weekend_runs: scheduleData.weekend_runs,
          timezone: scheduleData.timezone,
          quiet_hours_start: scheduleData.quiet_hours_start,
          quiet_hours_end: scheduleData.quiet_hours_end,
        });
        setNextRuns(nextData.next_runs);
      } catch (e) {
        setScheduleError(e instanceof ApiError ? e.message : "Failed to load schedule config");
      } finally {
        setScheduleLoading(false);
      }
    }
    loadSchedule();
  }, []);

  // Cleanup detect error timer on unmount
  useEffect(() => {
    return () => {
      if (detectErrorTimerRef.current) {
        clearTimeout(detectErrorTimerRef.current);
      }
      if (ntfyTestPollRef.current) {
        clearInterval(ntfyTestPollRef.current);
      }
    };
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

  // Schedule configuration handlers
  function handleAddTime() {
    setScheduleForm((f) => ({ ...f, times: [...f.times, "12:00"] }));
    setScheduleValidationError(null);
  }

  function handleRemoveTime(index: number) {
    setScheduleForm((f) => ({
      ...f,
      times: f.times.filter((_, i) => i !== index),
    }));
  }

  function handleTimeChange(index: number, value: string) {
    setScheduleForm((f) => ({
      ...f,
      times: f.times.map((t, i) => (i === index ? value : t)),
    }));
  }

  async function handleScheduleSave(e: React.FormEvent) {
    e.preventDefault();
    setScheduleError(null);
    setScheduleSuccess(false);
    setScheduleValidationError(null);

    // Client-side validation: prevent saving with zero times in specific_times mode
    if (scheduleForm.mode === "specific_times" && scheduleForm.times.length === 0) {
      setScheduleValidationError("At least one run time is required in Specific Times mode.");
      return;
    }

    setScheduleSaving(true);
    try {
      const updated = await updateScheduleConfig(scheduleForm);
      setScheduleForm({
        mode: updated.mode,
        times: updated.times,
        interval_hours: updated.interval_hours,
        window_start: updated.window_start,
        window_end: updated.window_end,
        weekend_runs: updated.weekend_runs,
        timezone: updated.timezone,
        quiet_hours_start: updated.quiet_hours_start,
        quiet_hours_end: updated.quiet_hours_end,
      });
      setScheduleSuccess(true);
      setTimeout(() => setScheduleSuccess(false), 2000);

      // Refresh next runs after saving
      fetchNextRuns();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setScheduleValidationError(e.detail || "Invalid schedule configuration");
      } else {
        setScheduleError(e instanceof ApiError ? e.message : "Failed to save schedule");
      }
    } finally {
      setScheduleSaving(false);
    }
  }

  async function fetchNextRuns() {
    setNextRunsLoading(true);
    try {
      const data = await getScheduleNext();
      setNextRuns(data.next_runs);
    } catch {
      // Silently fail — next runs are informational
    } finally {
      setNextRunsLoading(false);
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
            <div className="flex gap-2">
              <input
                type="text"
                value={ntfyForm.lan_base_url ?? ""}
                onChange={(e) => setNtfyForm((f: NtfyConfigUpdate) => ({ ...f, lan_base_url: e.target.value || null }))}
                placeholder="e.g., 192.168.1.100:7432"
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

        {/* Ntfy Connection Test */}
        <div className="border-t border-gray-100 pt-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-900">Test Connection</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Sends a test notification with a confirm button. Tap it on your phone to verify.
              </p>
            </div>
            <button
              type="button"
              onClick={handleNtfyTest}
              disabled={ntfyTesting}
              className="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors inline-flex items-center gap-1.5"
            >
              {ntfyTesting && (
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
              Send Test
            </button>
          </div>

          {/* Test result feedback */}
          {ntfyTestResult === "sent" && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-700 flex items-center gap-2">
              <svg className="animate-pulse h-4 w-4 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
              Notification sent — waiting for you to tap "Confirm Connection" on your phone...
            </div>
          )}

          {ntfyTestResult === "confirmed" && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-sm text-green-700 flex items-center gap-2">
              <svg className="h-4 w-4 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
              Connection confirmed — ntfy notifications are working correctly.
            </div>
          )}

          {ntfyTestResult === "failed" && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
              Test failed: {ntfyTestError}
            </div>
          )}
        </div>
      </section>

      {/* Schedule Configuration */}
      <section className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-gray-900">Pipeline Schedule</h3>
          <span className="text-xs text-gray-400">When to run the pipeline</span>
        </div>

        {scheduleError && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
            {scheduleError}
          </div>
        )}

        {scheduleValidationError && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
            {scheduleValidationError}
          </div>
        )}

        {scheduleLoading ? (
          <div className="space-y-3 animate-pulse">
            <div className="h-10 bg-gray-200 rounded-lg" />
            <div className="h-10 bg-gray-200 rounded-lg" />
            <div className="h-10 bg-gray-200 rounded-lg" />
          </div>
        ) : (
          <form onSubmit={handleScheduleSave} className="space-y-4">
            {/* Mode Toggle */}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1.5">Schedule Mode</label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setScheduleForm((f) => ({ ...f, mode: "specific_times" }))}
                  className={`flex-1 px-3 py-2 text-sm font-medium rounded-lg border transition-colors ${
                    scheduleForm.mode === "specific_times"
                      ? "bg-blue-600 text-white border-blue-600"
                      : "bg-white text-gray-700 border-gray-200 hover:bg-gray-50"
                  }`}
                >
                  Specific Times
                </button>
                <button
                  type="button"
                  onClick={() => setScheduleForm((f) => ({ ...f, mode: "interval" }))}
                  className={`flex-1 px-3 py-2 text-sm font-medium rounded-lg border transition-colors ${
                    scheduleForm.mode === "interval"
                      ? "bg-blue-600 text-white border-blue-600"
                      : "bg-white text-gray-700 border-gray-200 hover:bg-gray-50"
                  }`}
                >
                  Interval
                </button>
              </div>
            </div>

            {/* Specific Times Mode */}
            {scheduleForm.mode === "specific_times" && (
              <div className="space-y-2">
                <label className="block text-xs font-medium text-gray-600">Run Times</label>
                {scheduleForm.times.map((time, index) => (
                  <div key={index} className="flex items-center gap-2">
                    <input
                      type="time"
                      value={time}
                      onChange={(e) => handleTimeChange(index, e.target.value)}
                      className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <button
                      type="button"
                      onClick={() => handleRemoveTime(index)}
                      className="px-2.5 py-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors"
                      title="Remove time"
                    >
                      ✕
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={handleAddTime}
                  className="w-full px-3 py-2 text-sm font-medium text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors"
                >
                  + Add Time
                </button>
                {scheduleForm.times.length === 0 && (
                  <p className="text-xs text-red-500">At least one run time is required.</p>
                )}
              </div>
            )}

            {/* Interval Mode */}
            {scheduleForm.mode === "interval" && (
              <div className="space-y-3">
                <FormField label="Run Every (hours)">
                  <input
                    type="number"
                    min={1}
                    max={24}
                    value={scheduleForm.interval_hours}
                    onChange={(e) =>
                      setScheduleForm((f) => ({ ...f, interval_hours: parseInt(e.target.value, 10) || 1 }))
                    }
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </FormField>
                <div className="grid grid-cols-2 gap-3">
                  <FormField label="Window Start">
                    <input
                      type="time"
                      value={scheduleForm.window_start}
                      onChange={(e) => setScheduleForm((f) => ({ ...f, window_start: e.target.value }))}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  </FormField>
                  <FormField label="Window End">
                    <input
                      type="time"
                      value={scheduleForm.window_end}
                      onChange={(e) => setScheduleForm((f) => ({ ...f, window_end: e.target.value }))}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  </FormField>
                </div>
                <p className="text-xs text-gray-400">
                  Pipeline runs every {scheduleForm.interval_hours} hour{scheduleForm.interval_hours !== 1 ? "s" : ""} between {scheduleForm.window_start} and {scheduleForm.window_end}.
                </p>
              </div>
            )}

            {/* Weekend Runs Toggle */}
            <div className="flex items-center justify-between bg-gray-50 rounded-lg border border-gray-100 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-gray-900">Weekend Runs</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Run the pipeline on Saturday and Sunday.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setScheduleForm((f) => ({ ...f, weekend_runs: !f.weekend_runs }))}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  scheduleForm.weekend_runs
                    ? "bg-blue-600 text-white"
                    : "bg-gray-200 text-gray-700"
                }`}
              >
                {scheduleForm.weekend_runs ? "ON" : "OFF"}
              </button>
            </div>

            {/* Quiet Hours */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="block text-xs font-medium text-gray-600">Quiet Hours</label>
                <button
                  type="button"
                  onClick={() =>
                    setScheduleForm((f) => ({
                      ...f,
                      quiet_hours_start: f.quiet_hours_start ? null : "22:00",
                      quiet_hours_end: f.quiet_hours_end ? null : "07:00",
                    }))
                  }
                  className={`px-2 py-1 text-xs font-medium rounded transition-colors ${
                    scheduleForm.quiet_hours_start
                      ? "bg-blue-600 text-white"
                      : "bg-gray-200 text-gray-700"
                  }`}
                >
                  {scheduleForm.quiet_hours_start ? "ON" : "OFF"}
                </button>
              </div>
              {scheduleForm.quiet_hours_start && (
                <div className="grid grid-cols-2 gap-3">
                  <FormField label="Start (notifications pause)">
                    <input
                      type="time"
                      value={scheduleForm.quiet_hours_start ?? "22:00"}
                      onChange={(e) => setScheduleForm((f) => ({ ...f, quiet_hours_start: e.target.value }))}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  </FormField>
                  <FormField label="End (batch delivery)">
                    <input
                      type="time"
                      value={scheduleForm.quiet_hours_end ?? "07:00"}
                      onChange={(e) => setScheduleForm((f) => ({ ...f, quiet_hours_end: e.target.value }))}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  </FormField>
                </div>
              )}
              <p className="text-xs text-gray-400">
                During quiet hours, notifications are queued and delivered as a batch summary when quiet hours end.
              </p>
            </div>

            {/* Next Upcoming Runs */}
            <div className="bg-gray-50 rounded-lg border border-gray-100 px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium text-gray-600">Next Scheduled Runs</p>
                {nextRunsLoading && (
                  <span className="text-xs text-gray-400">Loading...</span>
                )}
              </div>
              {nextRuns.length > 0 ? (
                <ul className="space-y-1">
                  {nextRuns.map((run, i) => (
                    <li key={i} className="text-sm text-gray-700">
                      {new Date(run).toLocaleString(undefined, {
                        weekday: "short",
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-gray-400">No upcoming runs scheduled.</p>
              )}
            </div>

            <button
              type="submit"
              disabled={scheduleSaving}
              className="w-full px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {scheduleSaving ? "Saving..." : scheduleSuccess ? "✓ Saved" : "Save Schedule"}
            </button>
          </form>
        )}
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
            <FormField label="Auto-Apply Score">
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
              <p className="text-xs text-gray-400 mt-1">
                Jobs scoring at or above this are auto-tailored and queued for you to apply. No review needed.
              </p>
            </FormField>
            <FormField label="Maybe Pile Score">
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
              <p className="text-xs text-gray-400 mt-1">
                Jobs between this and the auto-apply score go to your review queue. Below this, they're skipped silently.
              </p>
            </FormField>
            <FormField label="Auto-Submit Score (Vision Agent)">
              <input
                type="number"
                min={0}
                max={101}
                value={form.external_apply_threshold}
                onChange={(e) =>
                  setForm((f: SettingsType) => ({ ...f, external_apply_threshold: parseInt(e.target.value, 10) || 0 }))
                }
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <p className="text-xs text-gray-400 mt-1">
                Jobs at or above this score attempt auto-submission via Vision Agent. Set to 101 to disable auto-submit entirely.
              </p>
            </FormField>
            <FormField label="Human Review Threshold (Vision Agent)">
              <input
                type="number"
                min={0}
                max={100}
                value={form.human_review_threshold ?? 85}
                onChange={(e) =>
                  setForm((f: SettingsType) => ({ ...f, human_review_threshold: parseInt(e.target.value, 10) || 85 }))
                }
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <p className="text-xs text-gray-400 mt-1">
                During auto-submit, jobs above this score pause for your review on open-ended questions. Irrelevant if Vision Agent is disabled.
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
