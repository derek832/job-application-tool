import { useState, useCallback } from "react";
import { getQueue } from "./api/client";
import { Navigation, type Page } from "./components/Navigation";
import { ConnectionError } from "./components/ConnectionError";
import { usePolling } from "./hooks/usePolling";
import { useBadge } from "./hooks/useBadge";
import type { ConnectionState } from "./types/connection";
import { Dashboard } from "./pages/Dashboard";
import { HumanQueue } from "./pages/HumanQueue";
import { JobHistory } from "./pages/JobHistory";
import { SearchConfig } from "./pages/SearchConfig";
import { GoalsProfile } from "./pages/GoalsProfile";
import { ProfileConfig } from "./pages/ProfileConfig";
import { Settings } from "./pages/Settings";

const POLL_INTERVAL_MS = 60_000;

function renderPage(page: Page): React.JSX.Element {
  switch (page) {
    case "dashboard":
      return <Dashboard />;
    case "queue":
      return <HumanQueue />;
    case "history":
      return <JobHistory />;
    case "search":
      return <SearchConfig />;
    case "goals":
      return <GoalsProfile />;
    case "profile":
      return <ProfileConfig />;
    case "settings":
      return <Settings />;
  }
}

export default function App() {
  const [activePage, setActivePage] = useState<Page>("dashboard");
  const [queueCount, setQueueCount] = useState(0);
  const [connection, setConnection] = useState<ConnectionState>({
    connected: true,
    lastConnectedAt: null,
    lastError: null,
  });

  const pollQueue = useCallback(async () => {
    try {
      const items = await getQueue();
      setQueueCount(items.length);
      setConnection({
        connected: true,
        lastConnectedAt: new Date().toISOString(),
        lastError: null,
      });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Unknown error";
      setConnection((prev) => ({
        connected: false,
        lastConnectedAt: prev.lastConnectedAt,
        lastError: message,
      }));
    }
  }, []);

  usePolling(pollQueue, POLL_INTERVAL_MS);
  useBadge(queueCount);

  return (
    <div className="flex h-screen bg-gray-50">
      <Navigation activePage={activePage} onNavigate={setActivePage} />
      <main className="flex-1 overflow-y-auto">
        {!connection.connected && (
          <ConnectionError
            lastConnectedAt={connection.lastConnectedAt}
            lastError={connection.lastError}
          />
        )}
        {renderPage(activePage)}
      </main>
    </div>
  );
}
