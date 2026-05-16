import { useState } from "react";
import { saveToken } from "../api/token-storage";

interface TokenPromptProps {
  onTokenSaved: () => void;
}

export function TokenPrompt({ onTokenSaved }: TokenPromptProps) {
  const [token, setToken] = useState("");

  function handleSave() {
    const trimmed = token.trim();
    if (!trimmed) return;
    saveToken(trimmed);
    onTokenSaved();
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-white rounded-lg shadow-md p-6">
        <h1 className="text-xl font-bold text-gray-900 mb-2">
          API Token Required
        </h1>
        <p className="text-sm text-gray-600 mb-4">
          Enter the Bearer token used to authenticate with the Job Application
          Tool backend. This is the same <code>API_TOKEN</code> value from your{" "}
          <code>.env</code> file.
        </p>
        <label
          htmlFor="token-input"
          className="block text-sm font-medium text-gray-700 mb-1"
        >
          Token
        </label>
        <input
          id="token-input"
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave();
          }}
          placeholder="Paste your API token"
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <button
          type="button"
          onClick={handleSave}
          disabled={!token.trim()}
          className="mt-4 w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Save
        </button>
      </div>
    </div>
  );
}
