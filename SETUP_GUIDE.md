# Complete Setup Guide — Job Application Tool

This guide walks a brand-new user through every step needed to go from zero to a fully running, personalized job application pipeline. It covers all external services, all configuration inside the app, and all the hardcoded code that needs to be tailored to your specific background and industry.

Estimated total setup time: **60–90 minutes** (mostly waiting for things to deploy and authorize).

---

## Table of Contents

1. [What You're Setting Up](#1-what-youre-setting-up)
2. [Prerequisites](#2-prerequisites)
3. [Step 1 — Clone and Create Your .env File](#3-step-1--clone-and-create-your-env-file)
4. [Step 2 — Anthropic (Claude AI)](#4-step-2--anthropic-claude-ai)
5. [Step 3 — Google Docs Resume](#5-step-3--google-docs-resume)
6. [Step 4 — Google Apps Script](#6-step-4--google-apps-script)
7. [Step 5 — Gmail OAuth (Notifications)](#7-step-5--gmail-oauth-notifications)
8. [Step 6 — ntfy Push Notifications (Recommended)](#8-step-6--ntfy-push-notifications-recommended)
9. [Step 7 — Docker First Build](#9-step-7--docker-first-build)
10. [Step 8 — Start Chrome for LinkedIn](#10-step-8--start-chrome-for-linkedin)
11. [Step 9 — Log Into LinkedIn](#11-step-9--log-into-linkedin)
12. [Step 10 — Configure the App (Web UI)](#12-step-10--configure-the-app-web-ui)
13. [Step 11 — Customize the AI Prompts (Code)](#13-step-11--customize-the-ai-prompts-code)
14. [Step 12 — Customize the Pre-filters (Code)](#14-step-12--customize-the-pre-filters-code)
15. [Step 13 — Dry Run and Calibration](#15-step-13--dry-run-and-calibration)
16. [Step 14 — Go Live](#16-step-14--go-live)
17. [Daily Usage Reference](#17-daily-usage-reference)
18. [Prompt Customization by Industry](#18-prompt-customization-by-industry)
19. [Troubleshooting](#19-troubleshooting)

---

## 1. What You're Setting Up

The tool runs entirely on your computer. Here's everything that's involved:

```
Your Computer
├── Docker (runs two containers)
│   ├── Automator — the Python brain: browses LinkedIn, calls Claude,
│   │               tailors your resume, submits applications
│   └── Frontend  — your web control panel at http://127.0.0.1:3000
├── Chrome (separate browser profile, runs in background)
│   └── Logged into LinkedIn — the automator remotely controls this session
└── data/ folder
    ├── state.db       — SQLite database (all jobs, history, config)
    ├── pdfs/          — tailored resume PDFs before submission
    ├── backups/       — daily DB snapshots
    └── chrome-ws-url.txt — written by the Chrome launch script
```

**External services you connect once:**

| Service | What it does | Cost |
|---|---|---|
| Anthropic Claude | Reads job descriptions, scores fit, tailors your resume | ~$1–5/month |
| Google Docs | Stores your resume; exports tailored PDFs | Free |
| Google Apps Script | Bridge between Docker and your Google Doc | Free |
| Gmail | Sends push notifications to your phone | Free |
| LinkedIn | Where the jobs come from (your existing account) | Free |
| ntfy.sh | Push notifications with action buttons on your phone | Free |

---

## 2. Prerequisites

Install these before anything else:

- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** — installs Docker and Docker Compose together. After install, open Docker Desktop and make sure the whale icon appears in your system tray and shows "Running."
- **[Google Chrome](https://www.google.com/chrome/)** — must be installed at the default path (`C:\Program Files\Google\Chrome\Application\chrome.exe` on Windows). The automation uses your existing Chrome installation.
- A **LinkedIn account** — you need to already be able to log into LinkedIn normally.
- A **Google account** (Gmail) — for the resume doc and notifications.

That's it. No Python, no Node.js, no terminal expertise needed beyond copying and pasting commands.

---

## 3. Step 1 — Clone and Create Your .env File

1. Download or clone this repository into a folder on your computer.
2. Inside the project folder, find the file named `.env.example`.
3. Make a copy of it in the same folder, named exactly `.env` (no `.example` extension).
4. Open `.env` in any text editor. It looks like this:

```
CLAUDE_API_KEY=
GMAIL_USER=
GOOGLE_APPS_SCRIPT_URL=
API_TOKEN=
DATA_DIR=./data
LOG_LEVEL=INFO
PLAYWRIGHT_TRACE=0
LAN_IP=
```

You'll fill in values as you work through the steps below. Leave `API_TOKEN` blank for now — the automator generates one automatically on first start.

> **Never commit `.env` to git.** It contains your API keys. The `.gitignore` already excludes it.

---

## 4. Step 2 — Anthropic (Claude AI)

Claude is the AI that reads job descriptions and scores them. This is the only paid service.

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an account (or log in)
3. Add a payment method (billing → add credit card). You'll need to add a small credit — $5 is more than enough for months of use.
4. Go to **API Keys** → **Create Key**
5. Copy the key (starts with `sk-ant-...`). You only see it once.
6. In your `.env` file, set:

```
CLAUDE_API_KEY=sk-ant-api03-...your-key-here...
```

**Cost expectations:** Expect roughly **$1–3 per day** during active job searching. Each scoring call costs a few cents; tailoring adds a bit more. The cost scales with how many jobs LinkedIn surfaces that pass the pre-filters — busy days with lots of new postings cost more than quiet days.

---

## 5. Step 3 — Google Docs Resume

Your resume lives in Google Docs. The tool reads it, makes a copy, applies ATS keyword replacements to the copy, exports that copy as a PDF, and deletes the copy. **Your original document is never modified.**

**Resume formatting requirements** (important for PDF quality):

- Use a clean, single-column format
- Bold formatting should only be on standalone elements: section headers and category labels (e.g., `**Security Operations:**`)
- The text *after* a bold label should be consistently non-bold. Mid-line bold-to-plain transitions cause the occasional PDF formatting artifact when text is replaced (it's a Google Apps Script limitation — it doesn't affect how ATS systems parse the text, only the visual PDF)
- No tables, no text boxes, no columns — the plain-text extraction won't handle those well
- Headers should be clear and consistent: `SUMMARY`, `CORE SKILLS`, `WORK EXPERIENCE`, `EDUCATION`, etc.

Once your resume is in Google Docs:

1. Open the document
2. Look at the URL: `https://docs.google.com/document/d/`**`1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms`**`/edit`
3. The bold part in the middle is your **Document ID** — save this for the next step.

---

## 6. Step 4 — Google Apps Script

This is a small piece of JavaScript you deploy to Google's servers. It acts as the bridge that lets the automator (running in Docker) read and export your Google Doc.

**Deploy it:**

1. Go to [script.google.com](https://script.google.com)
2. Click **New Project**
3. Delete any default code in the editor
4. Open the file `gas/Code.gs` from this project in a text editor, copy all of its contents, and paste it into the Apps Script editor
5. Click **Deploy** → **New deployment**
6. Click the gear icon next to **Type** and select **Web App**
7. Set:
   - **Execute as:** Me
   - **Who has access:** Anyone
8. Click **Deploy**
9. If prompted, click **Authorize access** → select your Google account → click **Allow**
10. Copy the **Web App URL** that appears. It looks like `https://script.google.com/macros/s/AKfyc.../exec`
11. In your `.env` file, set:

```
GOOGLE_APPS_SCRIPT_URL=https://script.google.com/macros/s/your-script-id/exec
```

**Set the Document ID in Script Properties:**

1. Back in the Apps Script editor, click the **gear icon (⚙)** on the left sidebar → **Project Settings**
2. Scroll down to **Script Properties**
3. Click **Add script property**
4. Key: `DOCUMENT_ID`
5. Value: the Document ID you copied in Step 3
6. Click **Save script properties**

---

## 7. Step 5 — Gmail OAuth (Notifications)

The tool emails notifications to your phone via your carrier's email-to-SMS gateway (e.g., `5551234567@vtext.com` for Verizon). Gmail authentication uses OAuth2 — you authorize it once, and the token is stored locally.

1. In your `.env` file, set:

```
GMAIL_USER=youraddress@gmail.com
```

2. Start the automator (Step 7 below) and then run the Gmail authorization flow:

```bash
docker compose exec automator python -m src.notifications.gmail_auth
```

3. This prints a URL. Open it in your browser, authorize access to Gmail, and paste the confirmation code back into the terminal.

4. The token is saved to `data/gmail_token.json`. You won't need to do this again unless the token expires or you revoke it.

> **Note:** SMS-via-email is a fallback. ntfy (Step 6) is recommended as the primary notification channel because it supports one-tap Approve/Reject buttons directly from the notification.

---

## 8. Step 6 — ntfy Push Notifications (Recommended)

ntfy sends push notifications to your phone. The key feature: notifications for borderline jobs include **Approve** and **Reject** buttons that trigger the pipeline without opening the web app.

**Phone setup:**

1. Install the **ntfy** app on your phone ([iOS](https://apps.apple.com/us/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy))
2. You don't need an account — ntfy.sh is a free public server

**App configuration (Settings page in the web UI — see Step 10):**

The Settings page has an ntfy section. You'll configure:
- **ntfy server URL:** `https://ntfy.sh` (or your self-hosted instance)
- **Default topic:** a secret random string for general notifications (e.g., `jobhunt-abc123def456` — use something hard to guess since topics are public on ntfy.sh)
- **Urgent topic:** a second secret random string for jobs needing your review (enables Approve/Reject action buttons)

**LAN IP for action buttons:**

The Approve/Reject buttons in notifications POST directly to your automator. For this to work from your phone, the automator needs to be reachable on your local network (not just `127.0.0.1`). Set your computer's LAN IP in `.env`:

```
LAN_IP=192.168.1.100
```

Find your LAN IP: open a terminal and run `ipconfig` (Windows) — look for the IPv4 address under your Wi-Fi or Ethernet adapter. It typically starts with `192.168.` or `10.0.`.

After setting up, use the **Test Notification** button on the Settings page to verify everything works.

---

## 9. Step 7 — Docker First Build

With `.env` filled in, build and start the containers:

```bash
docker compose build
docker compose up -d
```

The first build takes 3–5 minutes (downloads base images, installs Python dependencies, downloads Playwright's browser). Subsequent starts are instant.

After starting, open [http://127.0.0.1:3000](http://127.0.0.1:3000) in your browser. You'll be prompted for your **API token**.

**Get your API token:**

On first start, the automator auto-generates a token and saves it to `.env`. Read it:

```bash
docker compose exec automator cat /app/data/.api_token 2>/dev/null || grep API_TOKEN .env
```

Or check the automator logs:

```bash
docker compose logs automator | grep -i "api.token\|token.generated"
```

Enter the token in the web app prompt. It's stored in your browser — you won't need to enter it again on this machine.

---

## 10. Step 8 — Start Chrome for LinkedIn

The automator controls a Chrome window on your computer to browse LinkedIn. A batch script handles this:

**Windows:** Double-click `start-chrome-debug.bat` in the project folder.

This opens a Chrome window using a separate profile (`AutomatorProfile`) so it doesn't interfere with your normal browsing. It also:
- Enables remote debugging on port 9222
- Saves the WebSocket URL to `data/chrome-ws-url.txt` so Docker can connect

You can minimize this Chrome window after it opens — it doesn't need to be in focus. **Don't close it** while the automator is running.

> **Every time you restart your computer**, you need to run `start-chrome-debug.bat` again before starting a pipeline run. Consider adding it to your Windows startup folder.

---

## 11. Step 9 — Log Into LinkedIn

In the Chrome window that `start-chrome-debug.bat` opened:

1. Navigate to [linkedin.com](https://linkedin.com) if it's not already there
2. Log into your LinkedIn account
3. Complete any 2FA prompts
4. Make sure you stay logged in — check the "Remember me" option if available

The automator uses this session. LinkedIn sessions typically stay valid for weeks. If the automator ever reports a "not logged in" error, just open the debug Chrome window and log back in.

**Important:** LinkedIn limits activity. The tool is designed to stay within normal human-like browsing limits (it's scheduled for weekdays 8am–8pm, runs a single batch per day by default, and includes randomized delays). Don't run multiple search cycles back-to-back manually unless testing.

---

## 12. Step 10 — Configure the App (Web UI)

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). Work through each settings page:

---

### Profile Page

Your personal info — used to pre-fill application forms.

| Field | What to enter |
|---|---|
| Full Name | Your legal name as it appears on your resume |
| Email | Your job-search email address |
| Phone | Your phone number |
| Location | Your city, state (e.g., "Austin, TX") |
| Work Authorization | e.g., "US Citizen", "Authorized to work in the US", "Requires H-1B sponsorship" |
| LinkedIn URL | Your full profile URL |
| Common Answers | Key-value pairs for frequent application questions (see below) |

**Common Answers** — pre-fill these to avoid Claude having to guess:

```
"years_of_experience": "7"
"willing_to_relocate": "No"
"salary_expectations": "120000"
"how_did_you_hear": "LinkedIn"
"us_citizen": "Yes"
"requires_sponsorship": "No"
"notice_period": "2 weeks"
```

---

### Goals Profile Page

This is the most important configuration. It tells Claude what you're looking for and shapes every scoring decision.

| Field | Guidance |
|---|---|
| **Target Titles** | List 5–10 specific job titles you'd accept. Be precise — "Security Engineer" and "Senior Security Engineer" are different. |
| **Industries** | Preferred industries (e.g., "Technology", "Healthcare", "Finance") |
| **Company Sizes** | e.g., "Startup (1-50)", "Mid-size (51-500)", "Enterprise (500+)" |
| **Location Preferences** | Specific cities, regions, or "Remote" |
| **Minimum Salary** | Integer, e.g., `110000`. Jobs with extractable salary info below this are filtered before Claude sees them. |
| **Deal Breakers** | Terms that auto-reject a job regardless of score. Examples: "Contract", "Associate", "Internship", "Clearance Required" |
| **Open to Stretch Roles** | If checked, jobs scoring 50–74 go to your human review queue instead of being auto-rejected. |
| **Career Objective** | 2–3 sentences describing what you're looking for and why. Claude uses this as context when scoring. |
| **Supplementary Context** | The most powerful field — see below. |

**Supplementary Context** is where you put everything that isn't on your resume but that Claude should know when scoring and tailoring. This text is never exported to PDFs — it's only used internally as context. Use it for:

- Recent projects not yet on your resume
- Skills you have but didn't list in the resume
- Specific achievements with numbers (revenue impact, team size, etc.)
- Career context ("I'm transitioning from X to Y")
- Things you want Claude to optimize for ("prioritize roles where I own the full security function")

Example (security/GRC professional):
```
Recent projects: Led SOC 2 Type II recertification for a 400-person SaaS company 
in Q1, reducing scope creep by 40%. Built an automated evidence collection 
workflow in Python that cut audit prep time by 60%.

Additional skills not on resume: Hands-on with Wiz, Lacework, and AWS Security Hub. 
Completed CISM exam prep (exam scheduled Q3).

Context: Looking to step up from player-coach to a dedicated security leadership role 
(CISO, VP Security, or Head of Security at a Series B-D company). Open to IC roles 
at Staff/Principal level if the scope is broad enough.
```

Example (product manager):
```
Recent launches: Led 0-to-1 launch of payment processing feature that drove $2.3M ARR 
in first 6 months. Managed cross-functional team of 12 across engineering, design, and data.

Additional context: Background spans B2B SaaS and marketplace models. Strongest in 
discovery and 0-to-1; less interested in pure optimization/growth PM roles.

Prefer companies with strong engineering culture where PM owns the what, not the how.
```

---

### Search Config Page

Controls what LinkedIn searches the automator runs.

| Field | Guidance |
|---|---|
| **Search Queries** | Add up to 10 keyword queries. Each runs as a separate LinkedIn search per cycle. |
| **Location** | City, state or "United States" for nationwide |
| **Job Type** | Full-time, Contract, Part-time, etc. |
| **Experience Level** | Entry, Associate, Mid-Senior, Director, Executive |
| **Remote Preference** | On-site, Hybrid, Remote, or leave blank for all |
| **Time Range** | "Past 24 hours" or "Past week" — recommended to prevent re-processing old jobs |
| **Sort By** | "Most Recent" recommended |

**Search query strategy:** Run multiple narrow queries rather than one broad one. The tool deduplicates across queries, so overlapping results aren't double-processed.

Example queries for a security professional:
```
"security manager"
"information security manager"
"CISO"
"head of security"
"director of security"
"security program manager"
"GRC manager"
```

Example queries for a product manager:
```
"senior product manager"
"principal product manager"
"group product manager B2B SaaS"
"product manager fintech"
```

---

### Settings Page

| Field | Guidance |
|---|---|
| **Claude API Key** | Should already be set via .env. Can also be entered here. |
| **Gmail User** | Your Gmail address |
| **GAS URL** | Your Google Apps Script deployment URL |
| **Good Fit Threshold** | Score ≥ this → auto-apply. Default: 75. Raise to 80 if you're getting too many auto-applies. Lower to 70 if barely anything qualifies. |
| **Stretch Threshold** | Score ≥ this → human review queue. Default: 50. Jobs below this are auto-skipped. |
| **External Apply Threshold** | Score ≥ this → attempt automated external ATS form fill. Default: 80. |
| **Human Review Threshold** | For external applies: score ≥ this → escalate to human queue for review before submitting. Default: 85. |
| **Dry Run** | Keep this ON during initial calibration. Jobs go through the full pipeline but aren't actually submitted. |
| **ntfy Config** | Server URL, default topic, urgent topic, LAN IP. Use Test button to verify. |
| **Pipeline Schedule** | Fixed at weekdays 8am–8pm Eastern. Contact Kiro to change the window. |

---

### Blacklist Page

Add company names or title patterns to permanently block. Use this when:
- You've already applied to a company through another channel
- A company is known to be a poor cultural fit
- A recruiter spam company keeps appearing

---

## 13. Step 11 — Customize the AI Prompts (Code)

This is the most important code-level customization. The scoring and tailoring prompts in `automator/src/agents/claude_client.py` contain **calibration notes written specifically for the original user's background** (cybersecurity/GRC professional with military background). Every new user must rewrite the calibration sections.

### The Scoring Prompt

Open `automator/src/agents/claude_client.py` and find `_SCORING_SYSTEM_PROMPT`.

The prompt has five scoring dimensions. The **calibration notes** within each dimension are what you need to rewrite. They currently say things like:

> *"Military IT/communications experience counts toward total career years at 66% weight"*
> *"Security and compliance work is highly cross-functional"*
> *"Government compliance frameworks: FedRAMP, StateRAMP, CMMC..."*

**What to change:**

Replace each calibration block with instructions relevant to your field. The structure to keep:
- The 5 dimensions and their 0-20 scales stay the same
- The rubric descriptions (16-20 = X, 12-15 = Y, etc.) stay the same  
- The `CALIBRATION:` paragraphs within each dimension are what you rewrite

See [Section 18](#18-prompt-customization-by-industry) for industry-specific examples of how these calibration notes should look.

**What each calibration block should communicate to Claude:**

1. **Skills & Tools — CALIBRATION:** What are the gaps in your background that Claude should know about? What technical things can you do vs. can't do? Where should it cap the score?

   > *"The candidate has deep experience in X and Y but limited hands-on Z. If Z is the primary job function (not just a nice-to-have), cap skills_match at 8/20."*

2. **Experience Level — CALIBRATION:** How should Claude interpret your years of experience? Any non-obvious experience counting rules?

   > *"The candidate has 4 years of formal PM experience plus 3 years as a technical lead who functioned as an informal PM. Count those 3 years at 75% weight for PM-specific requirements."*

3. **Domain Transferability — CALIBRATION:** What transfers well from your background, and what doesn't transfer at all? This is where Claude needs the most guidance.

   > *"Financial services and healthcare compliance transfer well to each other — 80%+ control overlap. Pure regulatory compliance background does NOT transfer to technical GRC roles requiring hands-on tool implementation."*

4. **Requirements Coverage — CALIBRATION:** Nothing to change here usually. The rubric is universal.

5. **Interview Likelihood — CALIBRATION:** Keep the suppressors (applying down, location, missing core skill). Adjust the career trajectory rule:

   > *"If the role type is fundamentally different from the candidate's career trajectory (e.g., IC engineer applying for pure management, or line manager applying for strategy/advisory roles): subtract 4 points."*

### The Tailoring Prompt

The `_TAILORING_SYSTEM_PROMPT` is mostly universal, but three rules reference specific resume structure:

```python
- Do NOT change the bold category labels before colons 
  (e.g. 'Security Operations:', 'Cloud & Infrastructure:')
- Do NOT replace the SUMMARY's first sentence (the bold/italic headline...)
- For the CORE SKILLS section, do NOT include the category label in your find string
```

Update these to match your resume's actual structure. If your resume uses different section names or layout patterns, describe them here. For example, if your resume doesn't have a "CORE SKILLS" section, remove that rule. If your summary has a different structure, update the description.

---

## 14. Step 12 — Customize the Pre-filters (Code)

Open `automator/src/pipeline/prefilter.py` and find `TITLE_NEGATIVE_SIGNALS`.

This is a hardcoded list of job title strings that are **immediately rejected** before Claude is even called. The current list reflects a security professional who doesn't want SaaS platform admin roles, pure engineering roles, or non-technical functions.

Review the list and:
- Remove entries that aren't relevant blocks for your field
- Add entries for roles you'd never apply to regardless of score

**Current list (for reference):**
```python
TITLE_NEGATIVE_SIGNALS = [
    "sailpoint", "servicenow developer", "servicenow admin",
    "workday developer", "workday consultant", ...
    "data scientist", "machine learning engineer", "ml engineer",
    "frontend developer", "backend developer", "full stack developer",
    "accountant", "financial analyst", "recruiter", "talent acquisition",
    "hr generalist", "marketing manager", "sales representative",
    "account executive", "customer success", "physical security",
]
```

After editing, rebuild the automator container:

```bash
docker compose build automator
docker compose up -d automator
```

---

## 15. Step 13 — Dry Run and Calibration

Before going live, run the pipeline in dry run mode and check that everything is working and scoring sensibly.

**Verify the pre-run checklist:**

Go to the Dashboard and check the Service Health section. All of these should show green:
- Chrome CDP connection
- Google Apps Script
- Claude API
- Gmail

If any are red, fix those first (see [Troubleshooting](#19-troubleshooting)).

**Run a preview:**

1. On the Dashboard, click **Preview Run** (not "Run Now")
2. This runs the full pipeline — discovery, pre-filtering, and scoring — but doesn't tailor resumes or submit applications
3. Results appear on the **Preview Results** page

**What to look for:**

- Are jobs being discovered? (If zero jobs found, check your search queries and Chrome/LinkedIn connection)
- Are the scores making sense? A job that obviously matches your background should score 70+. A job that obviously doesn't match should score below 50.
- Are jobs you'd want being pre-filtered out? (Check logs: `docker compose logs automator --follow`)
- Are jobs you'd never want passing through to scoring? (Add them to TITLE_NEGATIVE_SIGNALS or deal-breakers)

**Use the Scoring Trial page** to test specific job descriptions:

1. Go to **Scoring Trial** in the web app
2. Paste a job description you know is a strong match → should score 75+
3. Paste a job description you know is a bad match → should score below 50
4. If scores don't match your expectations, revisit the scoring prompt calibration

**Iterate:** Adjust thresholds and scoring prompt calibration until the tool's assessment roughly matches your own judgment on 10–15 representative jobs. This calibration step is worth the time — a well-calibrated scoring prompt means fewer wasted applications and fewer good jobs slipping past.

---

## 16. Step 14 — Go Live

Once the preview looks good:

1. Go to **Settings** and turn off **Dry Run**
2. Click **Run Now** on the Dashboard (or wait for the next scheduled run)
3. Monitor the first live run: `docker compose logs automator --follow`

The first real run will:
1. Search LinkedIn for matching jobs
2. Pre-filter by title and keywords
3. Score with Claude
4. Auto-apply to jobs scoring ≥ 75 (or your threshold) — this means tailoring your resume and submitting the LinkedIn Easy Apply form
5. Put borderline jobs (50–74) in the Human Queue with a phone notification
6. Skip everything below 50

**Check the Human Queue** after the first run and process any pending items. Approving a queued job triggers tailoring and application immediately.

---

## 17. Daily Usage Reference

On a normal day, this tool requires less than 5 minutes of your attention.

**When you get a notification:** A job needs your review. Open the notification — if it has Approve/Reject buttons, tap them directly. Otherwise, open `http://127.0.0.1:3000` → Human Queue.

**Start Chrome each day** (if you restarted your computer): Double-click `start-chrome-debug.bat`.

**Check the dashboard occasionally:** The Dashboard shows today's run summary, any errors, and cost tracking.

**Commands:**

| What | Command |
|---|---|
| Start everything | `docker compose up -d` |
| Stop everything | `docker compose down` |
| Watch live logs | `docker compose logs automator --follow` |
| Rebuild after code changes | `docker compose build automator` then `docker compose up -d automator` |
| Check database | Open Job History in the web app |

---

## 18. Prompt Customization by Industry

This section shows how the scoring prompt calibration notes should look for different professional backgrounds. Use these as templates for your own.

The structure is always the same: find the `CALIBRATION:` block within each dimension in `_SCORING_SYSTEM_PROMPT` and replace it with your version.

---

### Software Engineer (Mid-Level, Backend Focus)

**Skills & Tools — CALIBRATION:**
```
CALIBRATION: The candidate has 5 years of backend experience (Python, Go, 
PostgreSQL, Redis, Kubernetes) but limited frontend experience. Apply this rule:
- If the role requires significant frontend work (React, Vue, Angular as primary 
  responsibility): cap skills_match at 8/20
- If frontend is ancillary (admin dashboards, internal tooling): no penalty
- Strong cloud skills (AWS, GCP) transfer well; Azure-specific roles may have 
  a 2-3 point gap on tooling
```

**Experience Level — CALIBRATION:**
```
CALIBRATION: The candidate has 5 years total engineering experience, 3 years at 
a senior IC level. For Staff/Principal roles (typically 8-10 years): score 
experience_level at 10-12 (one level below, credible stretch). For pure management 
roles with no IC component: cap experience_level at 8/20.
```

**Domain Transferability — CALIBRATION:**
```
CALIBRATION: Backend engineering transfers well across most domains — financial 
services, healthcare, e-commerce, SaaS all use similar patterns. Score 15+ unless 
the role has deep domain-specific requirements (e.g., trading systems, medical 
device firmware, embedded systems). Fintech compliance engineering and healthcare 
engineering have regulatory overhead the candidate hasn't faced — score 
domain_transferability 3-4 points lower for roles where regulatory compliance 
IS the primary complexity driver.
```

---

### Product Manager (B2B SaaS)

**Skills & Tools — CALIBRATION:**
```
CALIBRATION: The candidate's PM work is entirely B2B SaaS — no hardware, 
marketplace, consumer/B2C, or platform/developer tooling experience. Apply:
- Consumer product roles (social, gaming, consumer apps): cap skills_match at 8/20
- Platform/developer tooling PM: 10-12 (adjacent, some transfer)
- B2B SaaS regardless of vertical: full score range applies
- The candidate uses standard PM tools (Jira, Figma, Amplitude, Mixpanel, SQL 
  for analysis). Deep data science or ML product experience is a gap.
```

**Domain Transferability — CALIBRATION:**
```
CALIBRATION: B2B SaaS PM experience transfers broadly across verticals 
(fintech → healthtech → security → HR tech all share similar buyer dynamics, 
enterprise sales cycles, and product motion). Score 14-16 for any B2B SaaS role.
Exception: Highly regulated verticals (medical devices, financial compliance products, 
government software) add process overhead the candidate hasn't navigated — score 
domain_transferability 3 points lower when regulatory approval processes ARE the 
product complexity, not just a constraint.
```

**Experience Level — CALIBRATION:**
```
CALIBRATION: The candidate is a senior IC PM (6 years, no direct reports). For 
roles with people management expectations:
- "PM who manages 1-2 junior PMs" (player-coach): cap at 14/20, credible stretch
- "Group PM / Director of Product managing a team of PMs": cap at 10/20, 
  significant stretch
- "VP of Product / CPO": cap at 6/20, wrong level
```

---

### Data Analyst / Business Intelligence

**Skills & Tools — CALIBRATION:**
```
CALIBRATION: The candidate has strong SQL and Python (pandas, matplotlib) skills 
and experience with Tableau and Looker. Apply these rules:
- Data engineering roles (building pipelines, dbt, Airflow, Spark) where pipeline 
  construction IS the job: cap skills_match at 8/20
- ML engineering or data science roles requiring model building: cap at 6/20
- BI/analytics/reporting roles: full score range applies
- The candidate can write complex SQL including window functions, CTEs, and 
  performance optimization — these skills transfer everywhere
```

**Domain Transferability — CALIBRATION:**
```
CALIBRATION: Data analytics skills transfer across all domains — the tools and 
methodology (SQL, dashboards, statistical analysis) are universal. Score based 
on whether the candidate would need domain ramp-up time, not on whether they've 
worked in that exact industry. 

Exception: Financial modeling and accounting analytics (GAAP reporting, variance 
analysis, FP&A) require finance-domain knowledge the candidate doesn't have — 
score domain_transferability at 6-8 for pure finance/FP&A analyst roles.
```

---

### Marketing / Growth

**Skills & Tools — CALIBRATION:**
```
CALIBRATION: The candidate has 4 years of growth marketing experience: paid 
social (Meta, Google Ads), email marketing, SEO, and marketing analytics. Apply:
- Performance/growth marketing roles: full score range
- Content marketing or brand roles (primarily creative/editorial): cap at 10/20
- Marketing engineering or martech platform admin roles: cap at 8/20
- Product marketing (positioning, messaging, sales enablement): 10-12, adjacent 
  but different primary skill set
```

---

### General Guidance for Any Field

When writing your calibrations, answer these four questions for each dimension:

1. **What can't you do** that commonly appears in job descriptions for your target roles? Where should Claude cap the score?
2. **What non-obvious experience do you have** that Claude might undercount? (Career pivots, adjacent work, informal roles)
3. **What transfers well** across industries/companies in your field? What doesn't?
4. **What level are you targeting**, and how should Claude handle roles that are one level above or below?

Write the calibration in plain English, as instructions to a recruiter who doesn't know you. Be specific — "cap at 8/20" is more useful to Claude than "score lower."

---

## 19. Troubleshooting

### Dashboard shows Chrome CDP as disconnected

1. Make sure `start-chrome-debug.bat` is running (not just Chrome — needs to be started through the script)
2. Check that `data/chrome-ws-url.txt` exists and has content
3. Restart the automator: `docker compose restart automator`
4. If that fails, stop Chrome, run the bat script again, restart the automator

### No jobs are being discovered

1. Are your LinkedIn search queries specific enough? Try searching the same query directly on LinkedIn — do results appear?
2. Is Chrome logged into LinkedIn? Open the debug Chrome window and check.
3. Check logs: `docker compose logs automator --follow` — look for scraper errors
4. LinkedIn's DOM sometimes changes. Check the logs for selector errors.

### All jobs are being scored too high / too low

- Too high (everything ≥ 75): Tighten the scoring prompt calibration. Add specific capping rules for skills or experience mismatches. Raise the `good_fit_threshold` temporarily.
- Too low (everything < 50): Your supplementary context may be too sparse — Claude doesn't know about skills/experience not on your resume. Add more to the Supplementary Context field. Check if your goals profile target titles match the jobs you're seeing.

### Resume tailoring produces garbled PDFs

- Check the Google Apps Script logs: script.google.com → your project → Executions
- Verify the `DOCUMENT_ID` is set correctly in Script Properties
- Make sure your Google Doc doesn't have tables, text boxes, or multi-column sections
- If bold formatting is bleeding: ensure bold transitions only happen at word boundaries in your original doc

### ntfy notifications not arriving

1. Click **Test Notification** on the Settings page — does it arrive?
2. If not, verify the ntfy server URL and topic name are correct
3. Make sure the ntfy app on your phone is subscribed to the same topic
4. For Approve/Reject buttons to work, `LAN_IP` must be set correctly in `.env` and your phone must be on the same network as your computer

### Docker won't start / port conflicts

- Port 3000 conflict: something else is using port 3000. Change the frontend port in `docker-compose.yml`: `"127.0.0.1:3001:3000"` and access at `http://127.0.0.1:3001`
- Port 7432 conflict: change the automator port: `"0.0.0.0:7433:7432"`
- If Docker Desktop isn't running: start it from the system tray / Start menu

### Gmail OAuth token expired

Re-run the authorization:
```bash
docker compose exec automator python -m src.notifications.gmail_auth
```

### Getting LinkedIn "security check" or CAPTCHA

LinkedIn occasionally challenges automated activity. If this happens:
1. Open the debug Chrome window
2. Manually complete the security check / CAPTCHA
3. The automator will resume normally on the next run

If it happens repeatedly, reduce the frequency of manual "Run Now" triggers and let the scheduled runs handle it.

---

*This guide covers the complete setup. For day-to-day questions or when something breaks, open the project in Kiro and describe what you're seeing — Kiro has full context of the codebase and can diagnose most issues directly.*
