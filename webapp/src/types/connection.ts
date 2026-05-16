/**
 * Connection state tracked in React component state.
 * Replaces chrome.storage.local connection tracking from the extension.
 */

export interface ConnectionState {
  connected: boolean;
  lastConnectedAt: string | null;
  lastError: string | null;
}
