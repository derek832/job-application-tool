# Job Application Tool

A system that automatically finds jobs on LinkedIn, decides if they're a good fit for you using AI, customizes your resume, and applies — all running privately on your own computer.

---

## What It Does

Every weekday, this tool:

1. Searches LinkedIn for new job postings matching your goals
2. Uses AI (Claude) to score how well each job fits your background
3. Automatically applies to strong matches with a tailored resume
4. Sends you a push notification for borderline jobs so you can decide
5. Skips anything that isn't a fit

You control everything through a web app at `http://127.0.0.1:3000` — a local dashboard where you can see what's happening, review jobs, and change your settings.

---

## How It Works

The tool runs inside Docker on your computer. Two containers work together: one does all the job-hunting work (the automator), and one serves the web interface (nginx). Nothing leaves your machine except calls to the services you explicitly configure.

```
Your Computer
├── Browser → http://127.0.0.1:3000 (your control panel)
├── Chrome (background, separate profile)
│   └── Logged into LinkedIn — the automator controls this session
└── Docker Compose
    ├── Frontend (nginx) — serves the web app + proxies API requests
    └── Automator (FastAPI + scheduler)
        ├── Browses LinkedIn for jobs via Chrome remote debugging
        ├── Pre-filters by title, keywords, and salary floor
        ├── Asks Claude to score each job fit (0-100)
        ├── Tailors your resume via Google Docs + Apps Script
        ├── Submits Easy Apply applications
        └── Notifies you via ntfy when your input is needed
```

---

## Privacy & Cost

- **Everything stays on your machine.** No data is sent anywhere except the services you explicitly set up.
- **Only one paid service:** Claude AI. Expect roughly **$1–3 per day** during active job searching, depending on how many jobs get scored and tailored.
- **All other services are free:** Docker, Google Docs, Google Apps Script, Gmail, LinkedIn, ntfy.

---

## Getting Started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- [Google Chrome](https://www.google.com/chrome/) installed at its default path — the automator controls a Chrome window to browse LinkedIn
- Any modern browser for the web dashboard (Chrome, Firefox, Edge, Safari all work)

No Node.js, Python, or other dev tools are needed. Everything runs inside Docker.

### Option A: Let Kiro Do It (Recommended)

[Kiro](https://kiro.dev) is a free AI coding assistant that can run all the setup commands for you.

1. Download and install [Kiro](https://kiro.dev) (free)
2. Open this project folder in Kiro
3. Say: **"Walk me through the complete setup from scratch"**

Kiro will handle every step it can and explain the parts that require you to click through browser-based authorization flows.

### Option B: Manual Setup

The full step-by-step guide is in:

```
SETUP_GUIDE.md
```

It covers every external service, every configuration screen in the app, and how to customize the AI prompts for your specific industry and background. Estimated time: 60–90 minutes.

---

## Starting the Tool

```bash
docker compose up -d
```

Then open [http://127.0.0.1:3000](http://127.0.0.1:3000). On your first visit you'll be prompted for your API token — this is the `API_TOKEN` value from your `.env` file (auto-generated on first start).

Before each pipeline run, Chrome needs to be running with remote debugging enabled. Double-click `start-chrome-debug.bat` to launch it.

---

## Web App Pages

| Page | What it's for |
|---|---|
| **Dashboard** | System status, Run Now, Preview Run, pause/resume, cost tracking, run history |
| **Human Queue** | Review borderline jobs — Approve & Tailor, or Skip |
| **Escalations** | External apply jobs with open-ended questions needing your review |
| **Job History** | Browse all discovered jobs with status and score filtering |
| **Search Config** | LinkedIn search queries, location, job type, experience level, remote preference |
| **Goals Profile** | Target titles, deal breakers, salary floor, career objective, supplementary context |
| **Profile** | Your contact info and pre-filled answers to common application questions |
| **Settings** | API keys, score thresholds, ntfy notifications, dry run toggle |
| **Blacklist** | Companies and title patterns to permanently block |
| **Scoring Trial** | Test Claude's scoring against any job description |
| **Preview Results** | Results from preview/dry runs before going live |

---

## Daily Usage

On a normal day this requires less than 5 minutes of attention.

**If you restarted your computer:** double-click `start-chrome-debug.bat` to relaunch the LinkedIn browser session before the pipeline runs.

**When you get a notification:** a job needs your review. Tap Approve or Reject directly from the ntfy notification, or open the Human Queue page in the web app.

**The pipeline runs automatically** on weekdays between 8am–8pm Eastern. Use Run Now on the Dashboard to trigger it manually.

---

## Resume Tailoring

The tool makes targeted keyword replacements in a copy of your Google Doc resume, exports it as a PDF, and submits that PDF. Your original document is never modified.

**One formatting note:** if your resume has bold text transitioning to non-bold mid-line (e.g., `**Category Label:** item one, item two`), replacements that span that boundary can inherit incorrect bold formatting in the exported PDF. This doesn't affect ATS parsing — it's purely visual. To avoid it, keep bold formatting on standalone elements only (section headers, labels before a colon) with consistently non-bold text following.

---

## Quick Commands

| What | Command |
|---|---|
| Start the tool | `docker compose up -d` |
| Stop the tool | `docker compose down` |
| Watch live logs | `docker compose logs automator --follow` |
| Rebuild after code changes | `docker compose build automator` then `docker compose up -d automator` |
| Rebuild everything | `docker compose build` then `docker compose up -d` |

---

## License

Private repository. Not for redistribution.
