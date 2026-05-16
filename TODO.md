# TODO — Job Application Tool

## Needs Testing / Debugging

- [ ] **Easy Apply automation** — Code is implemented (`easy_apply_stage.py`) but untested in production. Handles LinkedIn's multi-step Easy Apply modal with form filling, resume upload, cover letter, and submission confirmation.
- [ ] **External apply edge cases** — Vision Agent works on BambooHR. Needs testing on Greenhouse, Lever, Workday, iCIMS. May need fixes for shadow DOM, custom React components, drag-and-drop file uploads.
- [ ] **ATS account creation** — Registration detection, Google OAuth, and email verification are implemented but untested on real sites.

## Features to Add

- [ ] **Replace SMS with ntfy.sh push notifications** — Verizon is shutting down vtext.com email-to-SMS by 03/2027 (already degraded). Switch to ntfy.sh for instant push notifications. Free, open source, iOS/Android app, custom sounds per topic, no account needed. Keep SMS as optional fallback for other carriers.
- [ ] **Application response tracking** — Add statuses like "interview_scheduled" or "response_received" that you can manually set, plus tracking response rates over time.
- [ ] **Application analytics dashboard** — Track applications over time, response rates, which job titles/companies convert to interviews.

## Known Issues / Low Priority

- [ ] **Company name selector fragile** — Works now but LinkedIn changes their DOM frequently. May need periodic updates to the CSS selectors.
- [ ] **Integration tests not written** — End-to-end pipeline tests (Easy Apply happy path, External Apply, Human Queue flow, retry exhaustion) are missing.
- [ ] **Update setup guide and steering files** — Out of date (references cookie cloning, old GDocs URL). Wait until closer to final.

## Completed ✓

- [x] **Salary range extraction** — Parse salary info from job descriptions ($120K-$150K, $60/hr, etc.), convert hourly to annual, filter out jobs below min_salary before scoring.
- [x] **Skip already-viewed jobs in discovery** — Detect and skip job cards marked as "Viewed". Configurable toggle in Settings (default: ON).
- [x] **Mark jobs as applied on LinkedIn** — After successful external submission, navigate back and click "Mark as applied".
- [x] **Remove stale features** — Removed cookie clone, login_linkedin.py, linkedin_auth.py, extraction_stage.py, old discover_jobs. 666 lines removed.
- [x] **Property-based tests** — All 16 Hypothesis tests implemented (100 examples each).
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
- [x] **Application notes audit trail** — JSON of fields filled, visible in extension.
- [x] **Apply type detection** — Detects Easy Apply vs External, captures external URL.
- [x] **Test endpoint** — `POST /jobs/{id}/test-apply?dry_run=true`.
- [x] **Pipeline runs every day** — Changed from Mon-Fri to daily, 8AM-8PM Eastern hourly.
- [x] **Deal-breaker matching contextual** — Claude handles with full context.
- [x] **Discovery + extraction combined** — One pass, clicks each card and reads right panel.
- [x] **Deduplication by company + title** — Saves Claude tokens.
- [x] **Chrome CDP connection** — Connects to user's Chrome via remote debugging.
- [x] **Settings seeded from .env** — Auto-populate on startup.
- [x] **SMS notifications working** — Fixed async, sends for stretch roles and boundary scores.
- [x] **All previous fixes** — Docker networking, Tailwind, Playwright version, Claude model ID, JSON parsing, extraction timeout, token storage, dry run, activity log, clickable links, expandable cards.
