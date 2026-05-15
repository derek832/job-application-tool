/**
 * Background service worker for the Job Application Tool extension.
 *
 * Uses chrome.alarms to poll the Automator's queue endpoint every 60 seconds.
 * Updates the toolbar badge with the pending queue count, and stores connection
 * state in chrome.storage.local for the popup to display error states.
 */

import type { ConnectionState } from "./types/connection";

const ALARM_NAME = "poll-queue";
const POLL_INTERVAL_MINUTES = 1;
const BASE_URL = "http://127.0.0.1:7432";

async function getToken(): Promise<string | null> {
  const result = await chrome.storage.local.get("api_token");
  const token = result.api_token;
  if (typeof token !== "string" || token.length === 0) {
    return null;
  }
  return token;
}

async function pollQueue(): Promise<void> {
  const token = await getToken();
  if (!token) {
    // No token configured — show nothing on badge
    await chrome.action.setBadgeText({ text: "" });
    return;
  }

  try {
    const response = await fetch(`${BASE_URL}/queue`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      await handleConnectionError(`HTTP ${response.status} ${response.statusText}`);
      return;
    }

    const data: unknown = await response.json();

    if (!Array.isArray(data)) {
      await handleConnectionError("Invalid response format");
      return;
    }

    const count = data.length;
    const badgeText = count > 0 ? String(count) : "";

    await chrome.action.setBadgeText({ text: badgeText });
    await chrome.action.setBadgeBackgroundColor({ color: "#2563EB" });

    // Update connection state — connected successfully
    const connectionState: ConnectionState = {
      connected: true,
      lastConnectedAt: new Date().toISOString(),
      lastError: null,
    };
    await chrome.storage.local.set({ connectionState });
  } catch {
    await handleConnectionError("Unable to reach the Automator service");
  }
}

async function handleConnectionError(errorMessage: string): Promise<void> {
  // Set badge to "!" with red background to indicate error
  await chrome.action.setBadgeText({ text: "!" });
  await chrome.action.setBadgeBackgroundColor({ color: "#DC2626" });

  // Preserve last-known connection timestamp
  const existing = await chrome.storage.local.get("connectionState");
  const previousState = existing.connectionState as ConnectionState | undefined;

  const connectionState: ConnectionState = {
    connected: false,
    lastConnectedAt: previousState?.lastConnectedAt ?? null,
    lastError: errorMessage,
  };
  await chrome.storage.local.set({ connectionState });
}

// Set up the alarm on install/startup
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: POLL_INTERVAL_MINUTES });
  // Run an initial poll immediately
  pollQueue();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: POLL_INTERVAL_MINUTES });
  pollQueue();
});

// Handle alarm fires
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    pollQueue();
  }
});
