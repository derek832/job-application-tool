# TODO — Job Application Tool

## Blocking — Needed for Full Pipeline

- [x] **Fix tailoring stage async bug** — `'coroutine' object has no attribute 'ok'` in tailoring stage. Same missing `await` pattern as the SMS fix.
- [x] **Re-authorize Google Apps Script** — GDocs returns 401. Need to re-deploy or re-authorize the Apps Script web app so resume tailoring and PDF export work.
- [x] **Multiple search queries per cycle** — Currently runs one search. Need to support all 4 queries ("Security engineer NOT devsecops", "GRC", "security manager", "cyber security") each cycle.
- [x] **High-match external apply workflow** — For 90%+ scores that aren't Easy Apply: tailor the resume (ATS-optimized PDF ready) BEFORE sending the SMS notification. The text should say "resume is ready, go apply" not "go tailor and apply." For stretch roles and lower scores, batch these for later review.
- [x] **Easy Apply automation** — Fill and submit LinkedIn Easy Apply forms using profile data + tailored resume PDF.
- [x] **External apply via Vision Agent** — For non-Easy Apply jobs, navigate to the external ATS, fill forms using DOM extraction + label matching. Escalate to human queue if CAPTCHA or unrecognized fields. Includes ATS account creation, Google OAuth, and email verification.

## Features to Add

- [x] **ATS optimization summary on job cards** — Show what changes Claude made to the resume for each job (keywords added, sections rewritten, etc.) in the expandable History card. Requires a new field or storing a diff/summary from the tailoring stage.
- [x] **Supplementary context document support** — Add a second Google Doc (or local file) containing weekly work notes/detailed experience that gets passed to Claude alongside the resume during scoring and tailoring. Keeps the resume clean for PDF export while giving Claude richer context for matching and keyword optimization.
- [ ] **Application response tracking** — Add statuses like "interview_scheduled" or "response_received" that you can manually set, plus tracking response rates over time.
- [ ] **Application analytics dashboard** — Track applications over time, response rates, which job titles/companies convert to interviews.
- [ ] **Salary range extraction** — Parse salary info from job descriptions when not in LinkedIn's structured data, use it for filtering.

## Known Issues / Needs Optimization

- [ ] **Company name selector fragile** — Works now but LinkedIn changes their DOM frequently. May need periodic updates to the CSS selectors.
- [ ] **Chrome debug session management** — The `start-chrome-debug.bat` writes a websocket URL that becomes stale if Chrome restarts. Need auto-detection or a health check before pipeline runs.
- [ ] **SMS notification content could be richer** — Currently truncated to 160 chars. Consider adding a link to the extension or a brief score/rationale snippet for stretch role notifications.
- [ ] **Property-based tests not written** — All 16 Hypothesis property tests from the spec are unimplemented (marked optional). Would increase confidence in edge cases for scoring, classification, and rate limiting.
- [ ] **Integration tests not written** — End-to-end pipeline tests (Easy Apply happy path, External Apply, Human Queue flow, retry exhaustion) are missing.

## Completed ✓

- [x] **Deal-breaker matching is now contextual** — Removed substring matching. Claude handles deal-breakers with full context (won't flag "associate" in "associate with teams").
- [x] **Job title/company extracted during discovery** — Combined discover+extract in one pass from the search results page. Clicks each card and reads the right panel.
- [x] **Scheduled time removed from settings** — Hardcoded to Mon-Fri 8am-8pm Eastern. No user-facing option needed.
- [x] **Backup directory removed from settings** — Hardcoded to `/app/data/backups`.
- [x] **Dry run limited to 5 jobs** — Caps discovery at 5 jobs in dry run mode to control costs.
- [x] **Deduplication by company + title** — Skips jobs where the same company already has a listing with the same title in the DB. Saves Claude tokens.
- [x] **Tailwind CSS compilation fixed** — Added `@tailwindcss/vite` plugin.
- [x] **Docker networking fixed** — App binds to `0.0.0.0` inside container; port mapping restricts to `127.0.0.1` on host.
- [x] **Chrome CDP connection** — Pipeline connects to user's Chrome via remote debugging. No headless login needed.
- [x] **Settings seeded from .env** — Claude API key, Gmail user, SMS gateway, GDocs URL auto-populate from environment variables on startup.
- [x] **Activity log on Dashboard** — Shows recent status transitions with 5-second polling.
- [x] **Clickable links in History and Queue** — Job titles link to LinkedIn listings.
- [x] **Expandable rationale cards** — Job History rows expand to show Claude's scoring explanation.
- [x] **Dry run toggle shows ON/OFF text** — Clear button instead of ambiguous slider.
- [x] **LinkedIn experience level mapping fixed** — Updated to current LinkedIn filter IDs (internship=1, entry=2, associate=3, mid-senior=4, director=5, executive=6).
- [x] **Claude model ID fixed** — Using `claude-sonnet-4-6` (available on the API key).
- [x] **JSON parsing fix for Claude responses** — Handles markdown code block wrapping in Claude's output.
- [x] **Extraction timeout fix** — No longer waits for `networkidle` (LinkedIn never reaches it). Waits for description element directly.
- [x] **Clone LinkedIn Session button** — Extension can export cookies to the automator (though CDP approach is preferred).
- [x] **Token storage abstraction** — Works with both `chrome.storage.local` and `localStorage` fallback.
- [x] **Run Now actually triggers pipeline** — Was only setting status before, now calls `trigger_now()`.
- [x] **SMS notifications working** — Fixed missing `await` on `send_sms`. Notifications send for stretch roles and boundary scores.
- [x] **Playwright version mismatch fixed** — Dockerfile installs same version as requirements.txt.
