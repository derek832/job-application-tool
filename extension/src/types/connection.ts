/**
 * Shared types for connection state between the background service worker
 * and popup UI components.
 */

export interface ConnectionState {
  connected: boolean;
  lastConnectedAt: string | null;
  lastError: string | null;
}
