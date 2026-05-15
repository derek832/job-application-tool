# TODO — Job Application Tool

## Needs Testing / Debugging

- [ ] **Easy Apply automation** — Code is implemented (`easy_apply_stage.py`) but untested in production. Handles LinkedIn's multi-step Easy Apply modal with form filling, resume upload, cover letter, and submission confirmation.
- [ ] **External apply edge cases** — Vision Agent works on BambooHR. Needs testing on Greenhouse, Lever, Workday, iCIMS. May need fixes for shadow DOM, custom React components, drag-and-drop file uploads.
- [ ] **ATS account creation** — Registration detection, Google OAuth, and email verification are implemented but untested on real sites.

## Features to Add

- [ ] **Skip already-viewed jobs in discovery** — During scraping, detect and skip job cards that LinkedIn marks as "Viewed" to avoid re-processing jobs the user has already seen manually.
- [ ] **Mark jobs as applied on LinkedIn** — After a successful external application submission, navigate back to the LinkedIn listing and click "Mark as applied" so LinkedIn's tracking stays in sync.
- [ ] **Application response tracking** — Add statuses like "interview_scheduled" or "response_received" that you can manually set, plus tracking response rates over time.
- [ ] **Application analytics dashboard** — Track applications over time, response rates, which job titles/companies convert to interviews.
- [ ] **Salary range extraction** — Parse salary info from job descriptions when not in LinkedIn's structured data, use it for filtering.

## Known Issues / Low Priority

- [ ] **Company name selector fragile** — Works now but LinkedIn changes their DOM frequently. May need periodic updates to the CSS selectors.
- [ ] **Property-based tests not written** — All 16 Hypothesis property tests from the spec are unimplemented (marked optional). Would increase confidence in edge cases for scoring, classification, and rate limiting.
- [ ] **Integration tests not written** — End-to-end pipeline tests (Easy Apply happy path, External Apply, Human Queue flow, retry exhaustion) are missing.

## Completed ✓

- [x] **Fix tailoring stage async bug** — Added missing `await` on `send_sms` in notification and scoring stages.
- [x] **Re-authorize Google Apps Script** — Redeployed with "Anyone" access, fixed `body.setText()` error with append+remove approach, added `follow_redirects=True` to httpx client.
- [x] **Multiple search queries per cycle** — `search_queries` list field with UI in extension. Pipeline iterates all queries with randomized inter-query delays (10-20s).
- [x] **High-match external apply workflow** — Configurable `external_apply_threshold` (default 80). Jobs above threshold auto-submit via Vision Agent; below get tailored PDF + SMS notification for manual apply.
- [x] **External apply via Vision Agent** — DOM-based form field extraction, label matching, resume PDF upload, multi-page handling, CAPTCHA detection, ATS account creation with Google OAuth and email verification.
- [x] **ATS optimization summary on job cards** — Tailoring replacements stored as JSON, visible in Job History with find→replace diff view.
- [x] **Supplementary context document support** — `supplementary_context` field on Goals Profile, passed to Claude during scoring and tailoring for richer keyword matching.
- [x] **Chrome debug session management** — Auto-discovers fresh websocket URL from `/json/version` when stored URL is stale. 3-strategy fallback (stored → discover → direct).
- [x] **SMS notification content enriched** — Now includes fit score percentage in the message.
- [x] **Randomized delays for anti-detection** — Card clicks (1.5-4s), page navigation (5-12s), inter-query (10-20s).
- [x] **AI-generated keyword pre-filter** — Claude extracts 20-30 keywords from profile on first run (cached until profile changes). Jobs must match ≥2 keywords to proceed to scoring.
- [x] **Format-preserving resume tailoring** — Copies original doc, applies find/replace via Apps Script (preserves fonts, bullets, headings), exports PDF, deletes copy.
- [x] **Debug mode (skip_discovery)** — `POST /run?skip_discovery=true` skips discovery and scoring, jumps straight to tailoring for approved jobs.
- [x] **PDF viewing** — `GET /jobs/{id}/pdf` serves tailored PDFs. Link in Job History.
- [x] **Application notes audit trail** — Vision Agent stores JSON of every field filled, visible in Job History as green "Application Submitted" card.
- [x] **Apply type detection** — Discovery detects Easy Apply vs External Apply from LinkedIn's button, captures external URL.
- [x] **Test endpoint** — `POST /jobs/{id}/test-apply?dry_run=true` fills form without submitting for verification.
- [x] **Deal-breaker matching is now contextual** — Claude handles deal-breakers with full context.
- [x] **Job title/company extracted during discovery** — Combined discover+extract in one pass.
- [x] **Deduplication by company + title** — Saves Claude tokens.
- [x] **Chrome CDP connection** — Pipeline connects to user's Chrome via remote debugging.
- [x] **Settings seeded from .env** — Auto-populate from environment variables on startup.
- [x] **SMS notifications working** — Fixed missing `await`. Notifications send for stretch roles and boundary scores.
- [x] **All previous fixes** — Docker networking, Tailwind, Playwright version, Claude model ID, JSON parsing, extraction timeout, token storage, dry run, activity log, clickable links, expandable cards.
