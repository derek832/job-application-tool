/**
 * Token storage abstraction.
 *
 * Uses chrome.storage.local when available (extension context),
 * falls back to localStorage for development or non-extension contexts.
 */

const STORAGE_KEY = "api_token";

function isChromeStorageAvailable(): boolean {
  return (
    typeof chrome !== "undefined" &&
    chrome.storage !== undefined &&
    chrome.storage.local !== undefined
  );
}

export async function saveToken(token: string): Promise<void> {
  if (isChromeStorageAvailable()) {
    await chrome.storage.local.set({ [STORAGE_KEY]: token });
  } else {
    localStorage.setItem(STORAGE_KEY, token);
  }
}

export async function loadToken(): Promise<string | null> {
  if (isChromeStorageAvailable()) {
    const result = await chrome.storage.local.get(STORAGE_KEY);
    const token = result[STORAGE_KEY];
    return typeof token === "string" && token.length > 0 ? token : null;
  }
  return localStorage.getItem(STORAGE_KEY) || null;
}

export function getStorageType(): string {
  return isChromeStorageAvailable() ? "chrome.storage.local" : "localStorage";
}
