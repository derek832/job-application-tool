/**
 * ConnectionError banner component.
 *
 * Displays a warning banner when the Automator service is unreachable.
 * Shows the last successful connection timestamp and error message.
 *
 * Auto-dismisses when connection restores — the parent component simply
 * stops rendering this component when `connected` becomes true.
 */

interface ConnectionErrorProps {
  lastConnectedAt: string | null;
  lastError: string | null;
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString();
}

export function ConnectionError({ lastConnectedAt, lastError }: ConnectionErrorProps) {
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
            {lastError ?? "Unable to connect to the Automator service."}
          </p>
          {lastConnectedAt && (
            <p className="mt-2 text-xs text-red-600">
              Last connected: {formatTimestamp(lastConnectedAt)}
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
