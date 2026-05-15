/**
 * ConnectionError component.
 *
 * Displays a clear error state when the Automator service is unreachable,
 * including the last-known connection timestamp.
 */

import { useEffect, useState } from "react";
import type { ConnectionState } from "../types/connection";

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString();
}

export function ConnectionError() {
  const [state, setState] = useState<ConnectionState | null>(null);

  useEffect(() => {
    // Load initial state
    chrome.storage.local.get("connectionState").then((result) => {
      if (result.connectionState) {
        setState(result.connectionState as ConnectionState);
      }
    });

    // Listen for changes
    const listener = (
      changes: { [key: string]: chrome.storage.StorageChange },
      areaName: string
    ) => {
      if (areaName === "local" && changes.connectionState) {
        setState(changes.connectionState.newValue as ConnectionState);
      }
    };

    chrome.storage.onChanged.addListener(listener);
    return () => chrome.storage.onChanged.removeListener(listener);
  }, []);

  // Don't render anything if connected or state not yet loaded
  if (!state || state.connected) {
    return null;
  }

  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-4">
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0">
          <svg
            className="h-5 w-5 text-red-600"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
              clipRule="evenodd"
            />
          </svg>
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-red-800">
            Automator Unreachable
          </h3>
          <p className="mt-1 text-sm text-red-700">
            {state.lastError ?? "Unable to connect to the Automator service."}
          </p>
          {state.lastConnectedAt && (
            <p className="mt-2 text-xs text-red-600">
              Last connected: {formatTimestamp(state.lastConnectedAt)}
            </p>
          )}
          <p className="mt-2 text-xs text-red-600">
            Ensure Docker is running and the Automator container is started.
          </p>
        </div>
      </div>
    </div>
  );
}
