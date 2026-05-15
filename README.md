# Job Application Tool

A privacy-first, locally-hosted job application automation system. It monitors LinkedIn for new job postings, scores them against your career goals using Claude AI, tailors your resume, and submits applications — all running on your own machine.

## What It Does

1. **Discovers** new LinkedIn job postings matching your search criteria (daily, Mon–Fri)
2. **Scores** each job for fit using Claude AI against your career goals and resume
3. **Auto-applies** to good-fit jobs (Easy Apply or external sites) with a tailored resume
4. **Queues** borderline ("stretch") roles for your manual review via a Chrome Extension
5. **Notifies** you via SMS when action is needed

Everything runs locally in Docker. Your data, credentials, and job history never leave your machine (except the explicit API calls to Claude, Gmail, and Google Docs that you configure).

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Your Machine                                        │
│                                                      │
│  Chrome Extension (React)  ←→  Docker: FastAPI :7432 │
│                                  ├── Playwright      │
│                                  ├── APScheduler     │
│                                  └── SQLite DB       │
└─────────────────────────────────────────────────────┘
         │                              │
         └──── localhost only ──────────┘
                                        │
                    External APIs (HTTPS):
                    • Claude (Anthropic) — AI scoring & tailoring
                    • Gmail — SMS notifications via email-to-SMS
                    • Google Apps Script — resume read/write/export
                    • LinkedIn — job discovery via Playwright
```

---

## Prerequisites

Before you start, you'll need accounts/access for:

| Service | What You Need | Free Tier? |
|---------|--------------|------------|
| [Kiro](https://kiro.dev) | AI dev environment to run setup commands | Yes |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Runs the automator container | Yes |
| [Anthropic](https://console.anthropic.com/) | Claude API key for AI scoring | Pay-per-use |
| [Google Cloud](https://console.cloud.google.com) | OAuth credentials for Gmail API | Yes |
| [Google Apps Script](https://script.google.com) | Hosts your resume read/write endpoint | Yes |
| [LinkedIn](https://linkedin.com) | Your account (you log in once via the browser) | Yes |
| [Chrome](https://www.google.com/chrome/) | For the control panel extension | Yes |
| [Git](https://git-scm.com/) | Clone this repo | Yes |
| [Node.js 18+](https://nodejs.org/) | Build the Chrome extension | Yes |
| [Python 3.11+](https://www.python.org/) | Run the Gmail auth script (one-time) | Yes |

---

## Setup Guide

> **Tip:** Set up a free [Kiro](https://kiro.dev) account, open this project folder, and have Kiro run the commands for you. Just paste each step into the chat.

### Step 1: Clone the Repository

```bash
git clone https://github.com/derek832/job-application-tool.git
cd job-application-tool
```

### Step 2: Create Your Environment File

```bash
copy .env.example .env
```

Open `.env` in a text editor and fill in the values as you complete the steps below. Leave `API_TOKEN` blank — it auto-generates on first run.

### Step 3: Get a Claude API Key

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create an account and add billing (pay-per-use, typically a few cents per job scored)
3. Go to **API Keys** → **Create Key**
4. Paste the key into your `.env` file:
   ```
   CLAUDE_API_KEY=sk-ant-...
   ```

### Step 4: Set Up Google Apps Script (Resume Management)

This lets the tool read, edit, and export your Google Doc resume as PDF.

1. Create a Google Doc that contains your base resume
2. Note the **Document ID** from the URL: `https://docs.google.com/document/d/<THIS_PART>/edit`
3. Go to [script.google.com](https://script.google.com) → **New Project**
4. Delete the default code and paste the contents of `gas/Code.gs` from this repo
5. Click the gear icon (Project Settings) → **Script Properties** → **Add**:
   - Key: `DOCUMENT_ID`
   - Value: your document ID from step 2
6. Click **Deploy** → **New deployment** → **Web App**:
   - Execute as: **Me**
   - Who has access: **Only myself**
7. Click **Deploy**, authorize when prompted, and copy the deployment URL
8. Paste the URL into your `.env`:
   ```
   GOOGLE_APPS_SCRIPT_URL=https://script.google.com/macros/s/.../exec
   ```

### Step 5: Set Up Gmail OAuth (SMS Notifications)

The tool sends you SMS notifications via Gmail's email-to-SMS gateway (e.g., `5551234567@tmomail.net`).

#### 5a: Create Google Cloud OAuth Credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. Go to **APIs & Services** → **Library** → search "Gmail API" → **Enable**
4. Go to **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
   - Application type: **Desktop app**
   - Name: anything (e.g., "Job Application Tool")
5. Download the JSON file and save it as:
   ```
   automator/data/gmail_credentials.json
   ```

#### 5b: Run the Authorization Flow

```bash
cd automator
pip install google-auth google-auth-oauthlib google-api-python-client
python authorize_gmail.py
```

A browser window will open. Sign in with the Gmail account you want to send from, and authorize. This saves a token to `automator/data/gmail_token.json`.

#### 5c: Set Your Gmail Address

In `.env`:
```
GMAIL_USER=your.email@gmail.com
```

### Step 6: Build and Start the Automator

```bash
docker compose build automator
docker compose up -d
```

Verify it's running:
```bash
docker compose logs automator
```

You should see the FastAPI server start on `127.0.0.1:7432`.

### Step 7: Get Your API Token

On first startup, the Automator generates a secure API token. Retrieve it from the logs:

```bash
docker compose logs automator | findstr "API_TOKEN"
```

Copy this token — you'll paste it into the Chrome Extension settings.

### Step 8: Build and Install the Chrome Extension

```bash
cd extension
npm ci
npm run build
```

Then load it in Chrome:
1. Open `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select the `extension/dist` folder

### Step 9: Configure the Extension

1. Click the extension icon in Chrome's toolbar
2. Go to **Settings**
3. Paste your API token from Step 7
4. Verify the connection shows "Connected"

### Step 10: Configure Your Job Search

Use the extension UI to set up:

- **Search Config** — keywords, location, job type, experience level, remote preference
- **Goals Profile** — target titles, industries, salary requirements, deal-breakers
- **Profile** — your name, email, phone, work authorization, common application answers

### Step 11: Log Into LinkedIn

The Automator uses a persistent browser session. On the first run, you'll need to log into LinkedIn manually through the Playwright browser. Trigger a manual run from the extension dashboard — if LinkedIn requires login, the system will pause and notify you.

---

## Daily Usage

Once set up, the tool runs automatically Monday–Friday at your configured time. You interact with it through the Chrome Extension:

- **Dashboard** — see status, trigger manual runs, pause/resume
- **Human Queue** — review stretch-fit jobs, approve or reject
- **Job History** — browse all discovered jobs, filter by status
- **Config pages** — adjust search criteria, goals, thresholds

You'll get SMS notifications when:
- A stretch-fit role needs your review
- An application fails and needs manual intervention
- A score lands on a threshold boundary
- The system encounters an error (e.g., Google Docs auth expired)

---

## Folder Structure

```
job-application-tool/
├── automator/          Python FastAPI backend (runs in Docker)
│   ├── src/            Application source code
│   ├── tests/          pytest test suite
│   ├── data/           Gmail credentials & token (gitignored)
│   └── Dockerfile
├── extension/          Chrome Extension (React + TypeScript)
│   ├── src/            Extension source
│   ├── public/         manifest.json
│   └── dist/           Built extension (load this in Chrome)
├── gas/                Google Apps Script source
│   └── Code.gs
├── docker-compose.yml
├── .env.example        Template for environment variables
└── .kiro/              Kiro specs and steering files
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Extension shows "Disconnected" | Make sure Docker is running: `docker compose up -d` |
| "Unauthorized" errors | Check your API token matches between logs and extension settings |
| Gmail notifications not sending | Re-run `python authorize_gmail.py` if the token expired |
| Google Docs errors | Re-deploy the Apps Script and update the URL in settings |
| LinkedIn login wall | Trigger a manual run, then log in through the Playwright browser session |
| Build fails | Make sure Docker Desktop is running and you have internet access |

### Viewing Logs

```bash
docker compose logs automator --follow
```

### Restarting

```bash
docker compose down
docker compose up -d
```

### Rebuilding After Code Changes

```bash
docker compose build automator
docker compose up -d
```

---

## Security Notes

- All traffic stays on `localhost:7432` — nothing is exposed to your network
- Credentials are stored locally in Docker volumes, never committed to git
- The Claude API key is the only paid service; usage is typically $1–5/month for moderate job searching
- LinkedIn session cookies persist in the Docker volume — treat your `data/` folder as sensitive
- The API token secures communication between the extension and the automator

---

## Using Kiro to Set This Up

If you're not comfortable running terminal commands, [Kiro](https://kiro.dev) can do it for you:

1. Install Kiro and sign up for a free account
2. Open this project folder in Kiro
3. Tell Kiro what step you're on, and it will run the commands, troubleshoot errors, and guide you through the browser-based steps (Google OAuth, Apps Script deployment, etc.)

For example, you can say:
- "Build the Docker container and start it"
- "Help me set up the Gmail OAuth credentials"
- "Build the Chrome extension"
- "Show me the API token from the logs"

Kiro has full context of this project's structure and can handle the technical steps while you focus on the account setup (Google Cloud, Anthropic, etc.).

---

## License

Private repository. Not for redistribution.
