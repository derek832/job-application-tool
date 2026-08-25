# Job Application Tool

A LinkedIn job search assistant that runs on your computer. It finds jobs, scores them against your background using AI, tailors your resume for the ones that fit, and puts everything in front of you to review — so the actual applying is fast and informed.

---

## What It Actually Does

Each pipeline run:

1. **Searches LinkedIn** for new job postings using your configured queries
2. **Pre-filters** by title, keyword presence in the description, and salary floor — without calling the AI
3. **Scores each surviving job** with Claude (0–100) across five dimensions: skills match, experience level, domain fit, requirements coverage, and interview likelihood
4. **Routes based on score:**
   - Strong fit (≥75 by default) → tailors your resume and notifies you it's ready
   - Borderline or stretch (50–74) → drops it in the Human Queue for your review
   - Below threshold → skipped
5. **Resume tailoring:** for strong-fit jobs, reads your Google Doc resume, generates targeted keyword replacements via Claude, exports a tailored PDF, then restores your original document
6. **Notifies you** via ntfy push notification when a job needs your attention or a resume is ready

**What it does not do:** submit applications. The pipeline ends with a tailored PDF and a notification. You review the job, download the PDF, and apply yourself — or approve it from the Human Queue and apply from there.

---

## How It Works

```
Your Computer
├── Chrome (separate profile, runs in background)
│   └── Logged into LinkedIn — automator controls this via remote debugging
└── Docker Compose
    ├── Frontend (nginx)  — web app at http://127.0.0.1:3000
    └── Automator (FastAPI + scheduler)
        ├── Connects to Chrome via CDP (port 9222)
        ├── Scrapes LinkedIn search results with Playwright
        ├── Pre-filters by title/keywords/salary
        ├── Scores with Claude API
        ├── Tailors resume via Google Apps Script → Google Docs → PDF
        └── Notifies via ntfy
```

The database is SQLite, stored locally at `data/state.db`. Nothing leaves your machine except calls to Anthropic, Google, and ntfy.

---

## External Services

| Service | Purpose | Cost |
|---|---|---|
| **Anthropic Claude** | Job scoring and resume tailoring | ~$1–3/day during active use |
| **Google Docs** | Stores your resume; source for tailoring | Free |
| **Google Apps Script** | Reads/copies/exports your Google Doc as PDF | Free |
| **ntfy** | Push notifications to your phone | Free |
| **LinkedIn** | Where the jobs come from | Free (your existing account) |

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- [Google Chrome](https://www.google.com/chrome/) at its default install path — used as the LinkedIn browser session
- A LinkedIn account you're already logged into
- A Google account (for Docs and Apps Script)
- An Anthropic account with API credit

---

## Setup

See **`SETUP_GUIDE.md`** for the complete walkthrough. It covers:

- Getting your Claude API key
- Setting up the Google Docs resume and deploying the Apps Script
- Configuring ntfy on your phone
- Building and starting Docker
- Running Chrome in debug mode
- All configuration screens in the web app
- How to customize the AI prompts for your specific background and industry

Estimated setup time: 60–90 minutes.

---

## Starting the Tool

**1. Start Chrome for LinkedIn:**

Double-click `start-chrome-debug.bat`. This opens a separate Chrome profile with remote debugging enabled and saves the connection URL to `data/chrome-ws-url.txt`. You need to do this each time you restart your computer.

**2. Start Docker:**

```bash
docker compose up -d
```

**3. Open the web app:**

[http://127.0.0.1:3000](http://127.0.0.1:3000)

On first visit you'll be prompted for your API token. Find it by running:

```bash
docker compose logs automator | findstr "token"
```

Or check `API_TOKEN` in your `.env` file after the first startup.

---

## Web App

| Page | What it's for |
|---|---|
| **Dashboard** | System status, run now, preview run, pause/resume, cost tracking, run history |
| **Human Queue** | Review borderline jobs — approve to trigger tailoring, or skip |
| **Escalations** | Jobs that hit errors or edge cases needing manual attention |
| **Job History** | All discovered jobs with status and score filtering |
| **Search Config** | LinkedIn search queries (up to 10), location, job type, experience, remote |
| **Goals Profile** | Target titles, deal breakers, salary floor, career objective, supplementary context |
| **Profile** | Your contact info and pre-filled answers to common application questions |
| **Settings** | Claude API key, GAS URL, score thresholds, ntfy config, dry run mode |
| **Blacklist** | Companies and title patterns to permanently block |
| **Scoring Trial** | Paste any job description and get an immediate Claude score |
| **Preview Results** | Results from preview runs (discovery + scoring only, no tailoring) |

---

## Pipeline Schedule

Runs automatically on weekdays between 8am–8pm Eastern. Use **Run Now** on the Dashboard to trigger manually. Use **Preview Run** to test discovery and scoring without triggering any tailoring or notifications.

---

## Resume Tailoring

The tailoring process:
1. Reads your Google Doc resume via Apps Script
2. Sends it to Claude with the job description → Claude returns a list of `{find, replace}` pairs (8–15 targeted substitutions to optimize for ATS keywords)
3. Apps Script copies your original doc, applies the replacements while preserving bold/italic formatting, exports the copy as PDF, and deletes the copy
4. The PDF is saved to `data/pdfs/`
5. Your original Google Doc is restored to its untouched state

Your original document is never modified.

---

## Quick Commands

| What | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop | `docker compose down` |
| Logs (live) | `docker compose logs automator --follow` |
| Rebuild automator | `docker compose build automator` then `docker compose up -d automator` |
| Rebuild all | `docker compose build` then `docker compose up -d` |

---

## License

Private repository. Not for redistribution.
