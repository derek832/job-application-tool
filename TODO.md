# TODO — Job Application Tool

## Current Status

Wave 0 (Web App Migration) is **complete and deployed**. The Chrome Extension has been replaced with a standalone React web app at `http://127.0.0.1:3000`. Both services start with `docker compose up`. Auth is handled server-side by nginx — no token prompt needed.

---

## Needs Testing / Debugging

- [ ] **Easy Apply automation** — Code is implemented (`easy_apply_stage.py`) but untested in production. Handles LinkedIn's multi-step Easy Apply modal with form filling, resume upload, cover letter, and submission confirmation.
- [ ] **External apply edge cases** — Vision Agent works on BambooHR. Needs testing on Greenhouse, Lever, Workday, iCIMS. May need fixes for shadow DOM, custom React components, drag-and-drop file uploads.
- [ ] **ATS account creation** — Registration detection, Google OAuth, and email verification are implemented but untested on real sites.
- [ ] **Integration tests** — End-to-end pipeline tests (Easy Apply happy path, External Apply, Human Queue flow, retry exhaustion) are missing.

---

## UX / Configuration Improvements

- [ ] **Common application answers as a Settings UI section** — Questions like "Do you reside in the US?", "Will you require sponsorship?", veteran status, EEO demographics, and "Have you previously worked for this company?" are currently buried in `common_answers` in the DB. These should be a dedicated section in the web app Settings page with sensible defaults (Yes/No for residency/sponsorship, decline-to-answer for demographics, protected veteran toggle). A new user shouldn't have to manually populate these — the setup wizard or Settings page should prompt for them.
- [ ] **Intermediate commits during pipeline run** — Jobs are invisible in the web app until the entire run completes (single transaction). Add commits after discovery and after each scoring batch so jobs appear in real-time.
- [ ] **Post-submission verification** — The pipeline declares `external_apply_success` after clicking Submit, but doesn't verify confirmation text/redirect. Add a check for "application submitted" / "thank you" / redirect to confirmation page before marking success.
- [x] **Run ID on job records** — Added `run_id` column to `job_records` (format: YYYYMMDD_HHMM). Filterable in Job History via API. Each pipeline run stamps its jobs.
- [x] **Score filter in Job History** — Added min/max score query params on `GET /jobs` and a min score input in the frontend. Color-coded score badges (green ≥75, yellow ≥50, red <50).
- [x] **DB-based dedup replacing "Viewed" badge** — Pre-loads job IDs from last 7 days at discovery start, skips known jobs before clicking/extracting. Removed unreliable DOM "Viewed" check.
- [ ] **Scoring weight strategy as a configurable workflow** — Currently the fit scoring prompt and thresholds (good_fit=65, stretch=50) are hardcoded for one user's priorities. For other users, there should be a guided workflow (in the setup wizard or Settings) that asks what matters most to them (title match, industry, remote, salary, company size, growth opportunity) and builds a weighting strategy that gets injected into the scoring prompt. Think of it as a "What matters to you?" questionnaire that produces a custom scoring rubric rather than one-size-fits-all.

---

## Feature Waves (Ranked by Priority)

### ~~Wave 0: Web App Migration~~ ✅ DONE
**Merged:** PR #8 — `feature/wave-0-web-app-migration`

- [x] Migrated React UI from extension to `webapp/` directory
- [x] Multi-stage Docker build (Node.js build → nginx serve, non-root, 73MB)
- [x] nginx reverse proxy (`/api/*` → FastAPI automator)
- [x] Server-side auth injection (nginx injects Bearer token, zero user friction)
- [x] Replace Chrome APIs with web equivalents (localStorage, setInterval, document.title badge)
- [x] Property-based tests for API client and hooks (fast-check, 4 properties)
- [x] Removed Chrome Extension entirely
- [x] Updated README and docker-compose

---

### ~~Wave 1: Notifications & Mobile~~ ✅ DONE
**Merged:** `feat/wave-1-notifications-mobile` + `feat/lan-auto-detect`

- [x] ntfy.sh client (httpx POST, two auto-generated topics: urgent + info)
- [x] Action buttons on notifications (approve/reject from phone over LAN)
- [x] Post-run plain-English summary (sent to info topic + displayed in Run History)
- [x] SMS retained as optional fallback
- [x] Shared 10/hour rate limit across both channels
- [x] LAN IP auto-detection endpoint (`GET /config/lan-detect`)
- [x] "Detect" button in Settings UI (one-click LAN IP population)
- [x] Docker Compose port 7432 exposed on 0.0.0.0 for LAN access
- [x] `LAN_IP` env var override for non-standard Docker setups

---

### Wave 2: New User Experience (~55-75 credits) ← NEXT
**Spec:** `.kiro/specs/wave-2-new-user-experience/`

Replace the 17-step SETUP_GUIDE.md with an in-app setup wizard. First-run gating, guided troubleshooting, and a diagnostics page. A non-technical user should go from `docker compose up` to fully operational without reading docs.

- [ ] 6-step setup wizard (Claude key → GAS URL → Gmail → Profile → Goals → Search)
- [ ] Each step validates live before allowing progression
- [ ] First-run gate (wizard is the only UI until setup is complete)
- [ ] Dashboard inline health banners with plain-English fix guidance
- [ ] Dedicated Diagnostics page with per-service checks

---

### ~~Wave 3: Pipeline Intelligence~~ ✅ DONE
**Merged:** `feat/wave-3-pipeline-intelligence`

- [x] Preview/dry-run mode (discovery + scoring only, promote jobs to real pipeline)
- [x] Session health monitoring (pre-flight Chrome CDP + LinkedIn session check)
- [x] Scheduling flexibility (multiple times/day, intervals, weekends, quiet hours)
- [x] Company/title blacklist (filter at discovery time, before scoring)
- [x] Chrome CDP setup automation (detect + one-click launch from web app)

---

### Standalone Features (Not Yet Spec'd)

- [ ] **Application response tracking** — Add statuses like "interview_scheduled" or "response_received" that you can manually set, plus tracking response rates over time.
- [ ] **Application analytics dashboard** — Track applications over time, response rates, which job titles/companies convert to interviews.

---

## Completed ✓

- [x] **Wave 3: Pipeline Intelligence** — Preview/dry-run mode, session health monitoring, flexible scheduling (specific times + interval + quiet hours), company/title blacklist, Chrome CDP setup automation. 843 tests passing.
- [x] **Wave 0: Web App Migration** — Chrome Extension replaced with React SPA + nginx in Docker. Server-side auth, zero-friction startup.
- [x] **Wave 1: Notifications & Mobile** — ntfy.sh push notifications, LAN server with action buttons, run summaries, LAN IP auto-detection with Detect button in Settings.
- [x] **Kiro specs & steering** — All wave specs (0-3) and steering files (product, engineering, domain) committed to repo.
- [x] **Company name selector hardened** — JSON-LD structured data (schema.org JobPosting) as primary source, DOM selectors as fallback.
- [x] **Salary range extraction** — Parse salary from descriptions, convert hourly to annual, filter below min_salary before scoring.
- [x] **Skip already-viewed jobs in discovery** — Detect and skip "Viewed" cards. Configurable toggle (default: ON).
- [x] **Mark jobs as applied on LinkedIn** — After successful external submission, navigate back and click "Mark as applied".
- [x] **Remove stale features** — Removed cookie clone, login_linkedin.py, linkedin_auth.py, extraction_stage.py, old discover_jobs. 666 lines removed.
- [x] **Property-based tests** — All 16 Hypothesis tests (automator) + 4 fast-check tests (webapp).
- [x] **Fix tailoring stage async bug** — Added missing `await` on `send_sms`.
- [x] **Re-authorize Google Apps Script** — Redeployed with "Anyone" access, fixed write errors, added redirect following.
- [x] **Multiple search queries per cycle** — `search_queries` list with UI. Randomized inter-query delays (10-20s).
- [x] **High-match external apply workflow** — Configurable `external_apply_threshold` (default 80).
- [x] **External apply via Vision Agent** — DOM-based form filling, resume PDF upload, multi-page, CAPTCHA detection, ATS account creation.
- [x] **ATS optimization summary on job cards** — Tailoring replacements visible in Job History with diff view.
- [x] **Supplementary context document support** — Extra context field passed to Claude for richer matching.
- [x] **Chrome debug session management** — Auto-discovers fresh websocket URL. 3-strategy fallback.
- [x] **SMS notification content enriched** — Includes fit score percentage.
- [x] **Randomized delays for anti-detection** — Card clicks (1.5-4s), pages (5-12s), queries (10-20s).
- [x] **AI-generated keyword pre-filter** — 20-30 keywords cached, jobs must match ≥2 to proceed.
- [x] **Format-preserving resume tailoring** — Copy doc, find/replace, export PDF, delete copy.
- [x] **Debug mode (skip_discovery)** — `POST /run?skip_discovery=true`.
- [x] **PDF viewing** — `GET /jobs/{id}/pdf` with link in Job History.
- [x] **Application notes audit trail** — JSON of fields filled, visible in web app.
- [x] **Apply type detection** — Detects Easy Apply vs External, captures external URL.
- [x] **Test endpoint** — `POST /jobs/{id}/test-apply?dry_run=true`.
- [x] **Pipeline runs every day** — Daily, 8AM-8PM Eastern hourly.
- [x] **Deal-breaker matching contextual** — Claude handles with full context.
- [x] **Discovery + extraction combined** — One pass, clicks each card and reads right panel.
- [x] **Deduplication by company + title** — Saves Claude tokens.
- [x] **Chrome CDP connection** — Connects to user's Chrome via remote debugging.
- [x] **Settings seeded from .env** — Auto-populate on startup.
- [x] **SMS notifications working** — Fixed async, sends for stretch roles and boundary scores.
- [x] **All previous fixes** — Docker networking, Tailwind, Playwright version, Claude model ID, JSON parsing, extraction timeout, token storage, dry run, activity log, clickable links, expandable cards.
