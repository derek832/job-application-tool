# Implementation Plan: Wave 0 — Web App Migration

## Overview

Migrate the Chrome Extension control panel to a standalone React SPA served by nginx in Docker. The existing extension components are ported with Chrome API calls swapped for standard web equivalents (localStorage, setInterval, document.title). The FastAPI Automator backend is unchanged. nginx acts as a reverse proxy, unifying static files and API under a single origin.

## Tasks

- [x] 1. Scaffold webapp project and configure build tooling
  - [x] 1.1 Initialize webapp directory with Vite + React + TypeScript
    - Create `webapp/` directory at project root
    - Initialize `package.json` with pinned dependencies: react, react-dom, zod, tailwindcss, @tailwindcss/vite, vite, @vitejs/plugin-react, typescript, eslint
    - Create `tsconfig.json` with strict mode enabled
    - Create `vite.config.ts` with React plugin and Tailwind
    - Create `index.html` entry point
    - Create `src/main.tsx` and `src/index.css` (Tailwind imports)
    - _Requirements: 3.2, 3.3, 3.4_

  - [x] 1.2 Create nginx configuration file
    - Create `webapp/nginx.conf` with: listen 3000, root /usr/share/nginx/html, `/api/` proxy_pass to `http://automator:7432/` (strips prefix), Authorization header forwarding, `/assets/` cache headers, SPA fallback `try_files $uri $uri/ /index.html`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 1.3 Create multi-stage Dockerfile for webapp
    - Stage 1 (build): `node:20.18.0-slim`, WORKDIR /app, COPY package files, `npm ci`, COPY source, `npm run build`
    - Stage 2 (serve): `nginx:1.27.3-alpine`, create non-root appuser, copy dist from build stage, copy nginx.conf, set permissions, USER appuser, EXPOSE 3000
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 1.4, 1.5_

  - [x] 1.4 Update docker-compose.yml with frontend service
    - Change automator `ports` to `expose: ["7432"]` (internal only)
    - Add `frontend` service: build context `./webapp`, ports `127.0.0.1:3000:3000`, depends_on automator, restart unless-stopped
    - _Requirements: 1.1, 1.2, 1.3, 1.6_

- [x] 2. Implement API client and core hooks
  - [x] 2.1 Create token-storage module (localStorage)
    - Create `webapp/src/api/token-storage.ts`
    - Implement `saveToken`, `loadToken`, `clearToken` using localStorage with key `jat_api_token`
    - Synchronous API — no Chrome storage dependency
    - _Requirements: 5.1, 5.2, 5.3, 14.1_

  - [x] 2.2 Port API client to use relative paths
    - Create `webapp/src/api/client.ts`
    - Copy all Zod schemas, types, and API functions from `extension/src/api/client.ts`
    - Change `BASE_URL` from `http://127.0.0.1:7432` to `/api`
    - Change `getToken()` from async chrome.storage to synchronous localStorage read
    - Keep all request/response validation logic identical
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.5_

  - [x] 2.3 Create usePolling hook
    - Create `webapp/src/hooks/usePolling.ts`
    - Implement `usePolling(callback, intervalMs, enabled)` using `setInterval`
    - Fire callback immediately on mount, then at interval
    - Clear interval on unmount or when disabled
    - _Requirements: 6.1, 6.4, 6.5, 14.2_

  - [x] 2.4 Create useBadge hook
    - Create `webapp/src/hooks/useBadge.ts`
    - Implement `useBadge(count)` that sets `document.title` to `(N) Job Application Tool` when count > 0, or `Job Application Tool` when count is 0
    - Reset title on unmount
    - _Requirements: 6.2, 6.3, 14.3_

  - [x] 2.5 Write property tests for API client and hooks
    - **Property 4: API Client Request Isolation** — verify all request URLs use relative `/api/` prefix
    - **Property 5: API Client Auth Header Inclusion** — verify Authorization header matches stored token
    - **Property 6: API Error Mapping** — verify non-2xx responses produce correct ApiError objects
    - **Property 7: Tab Title Badge Formatting** — verify title format for any non-negative integer count
    - **Validates: Requirements 4.1, 4.2, 4.4, 5.5, 6.2, 6.3**

- [x] 3. Implement connection state and shared components
  - [x] 3.1 Create connection state type and ConnectionError banner
    - Create `webapp/src/types/connection.ts` with `ConnectionState` interface
    - Create `webapp/src/components/ConnectionError.tsx` — displays error banner with last connected timestamp
    - Banner visible across all views when `connected === false`
    - Auto-dismisses when connection restores
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [x] 3.2 Create TokenPrompt component
    - Create `webapp/src/components/TokenPrompt.tsx`
    - Renders when no token in localStorage
    - Provides input field and save button
    - On save, calls `saveToken()` and triggers app re-render
    - _Requirements: 5.4_

  - [x] 3.3 Create Navigation sidebar component
    - Create `webapp/src/components/Navigation.tsx`
    - Port the icon sidebar from `extension/src/App.tsx`
    - Support all 7 views: Dashboard, Queue, History, Search, Goals, Profile, Settings
    - Highlight active page, tooltip on hover
    - _Requirements: 3.1, 3.5_

- [x] 4. Checkpoint — Verify core infrastructure
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement page views
  - [x] 5.1 Port Dashboard page
    - Create `webapp/src/pages/Dashboard.tsx`
    - Port from `extension/src/pages/Dashboard.tsx`
    - Display: system status indicator, summary stats, Run Now button, Pause/Resume toggle, health indicators, last/next run timestamps, activity log
    - Use `usePolling` for status refresh at 60s interval
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

  - [x] 5.2 Port Human Queue page
    - Create `webapp/src/pages/HumanQueue.tsx`
    - Port from `extension/src/pages/HumanQueue.tsx`
    - Display queue items with: job title, company, LinkedIn URL, reason, fit score, fit rationale, timestamp
    - Implement Approve, Reject, Mark as Applied actions
    - Show error on action failure without removing item
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 5.3 Port Job History page
    - Create `webapp/src/pages/JobHistory.tsx`
    - Port from `extension/src/pages/JobHistory.tsx`
    - Display job list with: title, company, status, fit score, apply type, discovered date
    - Implement text search filter, status dropdown filter, pagination
    - Show full job details on selection
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 5.4 Port Search Config page
    - Create `webapp/src/pages/SearchConfig.tsx`
    - Port from `extension/src/pages/SearchConfig.tsx`
    - Editor for: keywords, search queries, location, job type, experience level, remote preference
    - Save via API, show success/error feedback
    - _Requirements: 12.1, 12.6, 12.7_

  - [x] 5.5 Port Goals Profile page
    - Create `webapp/src/pages/GoalsProfile.tsx`
    - Port from `extension/src/pages/GoalsProfile.tsx`
    - Editor for: target titles, industries, company sizes, geo prefs, min salary, deal-breakers, open to stretch, career objective, supplementary context
    - Save via API, show success/error feedback
    - _Requirements: 12.2, 12.6, 12.7_

  - [x] 5.6 Port Profile Config page
    - Create `webapp/src/pages/ProfileConfig.tsx`
    - Port from `extension/src/pages/ProfileConfig.tsx`
    - Editor for: full name, email, phone, location, work auth, LinkedIn URL, common answers (key-value pairs)
    - Save via API, show success/error feedback
    - _Requirements: 12.3, 12.6, 12.7_

  - [x] 5.7 Port Settings page
    - Create `webapp/src/pages/Settings.tsx`
    - Port from `extension/src/pages/Settings.tsx`
    - Editor for: Claude API key, Gmail user, SMS gateway, Google Docs URL, thresholds, toggles, backup dir, dry run
    - Separate section for Bearer token entry (saves to localStorage)
    - Save via API, show success/error feedback
    - _Requirements: 12.4, 12.5, 12.6, 12.7, 5.2_

- [x] 6. Wire App root component with routing, polling, and badge
  - [x] 6.1 Create App.tsx with full integration
    - Create `webapp/src/App.tsx`
    - Integrate Navigation, TokenPrompt, ConnectionError components
    - Implement connection state management (useState)
    - Use `usePolling` to poll queue endpoint every 60s
    - Use `useBadge` with queue count
    - Show TokenPrompt when no token, otherwise show Navigation + active page
    - Update connection state on API success/failure
    - _Requirements: 3.1, 3.5, 4.5, 5.4, 6.1, 6.4, 13.1, 13.3, 13.4, 14.4_

- [x] 7. Checkpoint — Verify full app builds and renders
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Remove Chrome Extension and update project
  - [x] 8.1 Delete extension directory and update .gitignore
    - Remove `extension/` directory entirely
    - Remove any extension-specific entries from `.gitignore`
    - Verify no Chrome Extension API references remain in active source
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 8.2 Update project documentation
    - Update `README.md` to reference the web app at `http://127.0.0.1:3000` as the sole UI
    - Remove all Chrome Extension setup instructions
    - Document `docker compose up` as the single startup command for both services
    - _Requirements: 7.4_

- [x] 9. Final checkpoint — Verify Docker Compose builds and runs
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The extension source in `extension/src/` is the starting point — most components port with minimal changes (swap Chrome APIs for web equivalents)
- The FastAPI Automator backend is completely unchanged
- Property tests validate correctness properties defined in the design document using fast-check
- nginx configuration is the critical integration piece — it unifies frontend and backend under one origin

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1"] },
    { "id": 2, "tasks": ["1.4", "2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["2.5", "3.1", "3.2", "3.3"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["8.1", "8.2"] }
  ]
}
```
