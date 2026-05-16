# Job Application Tool

A system that automatically finds jobs on LinkedIn, decides if they're a good fit for you using AI, customizes your resume, and applies — all running privately on your own computer.

---

## What It Does

Every weekday, this tool:

1. Searches LinkedIn for new job postings matching what you're looking for
2. Uses AI (Claude) to read each job and score how well it fits your goals
3. Automatically applies to good-fit jobs with a tailored resume
4. Texts you about borderline jobs so you can decide
5. Skips jobs that aren't a match

You control everything through a web app at `http://127.0.0.1:3000` — a local dashboard in your browser where you can see what's happening, review jobs, and change your preferences.

---

## How It Works

The tool runs inside Docker on your computer. Two containers work together: one does all the job-hunting work (the automator), and one serves the web interface you interact with (nginx). Nothing is shared with the outside world except the specific services you connect (AI scoring, Gmail for texts, Google Docs for your resume).

```
Your Computer
├── Browser → http://127.0.0.1:3000 (your control panel)
└── Docker Compose
    ├── Frontend (nginx) — serves the web app + proxies API requests
    └── Automator (FastAPI)
        ├── Browses LinkedIn for jobs
        ├── Asks AI to score each job
        ├── Edits your resume in Google Docs
        ├── Applies to jobs automatically
        └── Texts you when it needs your input
```

---

## Privacy & Cost

- **Everything stays on your machine.** No data is sent anywhere except the services you explicitly set up.
- **Only one paid service:** Claude AI costs roughly $1–5/month depending on how many jobs get scored.
- **All other services are free:** Docker, Gmail, Google Docs, Google Apps Script, LinkedIn.

---

## Getting Started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- A modern web browser (Chrome, Firefox, Edge, Safari — any will work)

No Node.js installation is needed. No browser extensions are needed. The web app is built entirely inside Docker.

### Option A: Let Kiro Do It (Recommended)

[Kiro](https://kiro.dev) is a free AI coding assistant that can run all the setup commands for you. You don't need to understand terminals, code, or any of the technical details.

1. Download and install [Kiro](https://kiro.dev) (free)
2. Open this project folder in Kiro
3. Say: **"Walk me through the complete setup from scratch"**

Kiro has a detailed setup guide built in and will handle every step it can — installing programs, running commands, building the tool, and explaining the parts that need you to click buttons in a browser (like creating accounts).

### Option B: Manual Setup

If you prefer to do it yourself, the full step-by-step guide is in:

```
SETUP_GUIDE.md
```

It assumes zero technical knowledge and explains every concept along the way.

---

## Starting the Tool

One command starts everything — both the backend automator and the web interface:

```bash
docker compose up -d
```

Then open your browser to:

```
http://127.0.0.1:3000
```

On your first visit, you'll be prompted to enter your API token. This is the same value as `API_TOKEN` in your `.env` file.

---

## Daily Usage (Once Set Up)

- **Dashboard** — see status, start a manual run, pause/resume
- **Human Queue** — review borderline jobs (approve or skip)
- **Job History** — browse everything the tool has found
- **Settings** — change what you're looking for, adjust thresholds

You'll get text messages when:
- A job needs your review
- An application failed and needs your help
- Something went wrong that the tool can't fix alone

---

## Resume Formatting Note

The ATS optimization works by making targeted text replacements in a copy of your Google Doc resume. Your original document is never modified. However, there's one thing to be aware of:

**Bold text boundaries:** If your resume has bold text that transitions to non-bold mid-line (e.g., "**Security Operations:** Vulnerability Management, Incident Response"), and Claude tries to replace text that spans that boundary, the replacement may inherit incorrect bold formatting in the exported PDF.

**How to avoid this:** Keep bold formatting limited to standalone elements (section headers, category labels before a colon). Make sure the text *after* a bold label is consistently non-bold. This way, replacements only happen within uniformly-formatted text and the PDF looks correct.

ATS parsers ignore formatting entirely — they only read the text. So even if bold bleeds slightly, it won't affect your application's chances. It's purely a visual issue in the PDF.

---

## Quick Commands

| What | Command |
|------|---------|
| Start the tool | `docker compose up -d` |
| Stop the tool | `docker compose down` |
| See what it's doing | `docker compose logs automator --follow` |
| See frontend logs | `docker compose logs frontend --follow` |
| Rebuild after updates | `docker compose build` then `docker compose up -d` |

Or just tell Kiro: "start the tool", "stop the tool", "show me the logs."

---

## License

Private repository. Not for redistribution.
