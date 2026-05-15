# Complete Setup Guide

This guide will walk you through every single step to get the Job Application Tool running on your Windows computer. It assumes you have never done anything like this before. Every concept is explained, every click is described.

**If you're using Kiro:** Just say "Walk me through the complete setup from scratch" and Kiro will follow this guide with you, running every command it can and telling you exactly what to do for the parts that need a browser.

---

## Table of Contents

1. [What You're About to Do (Big Picture)](#step-0-what-youre-about-to-do)
2. [Install Git](#step-1-install-git)
3. [Download This Project](#step-2-download-this-project)
4. [Install Docker Desktop](#step-3-install-docker-desktop)
5. [Install Node.js](#step-4-install-nodejs)
6. [Install Python](#step-5-install-python)
7. [Create Your Settings File](#step-6-create-your-settings-file)
8. [Get a Claude AI Key](#step-7-get-a-claude-ai-key)
9. [Set Up Google Apps Script (Resume)](#step-8-set-up-google-apps-script)
10. [Set Up Gmail Notifications](#step-9-set-up-gmail-notifications)
11. [Build and Start the Tool](#step-10-build-and-start-the-tool)
12. [Get Your API Token](#step-11-get-your-api-token)
13. [Build the Chrome Extension](#step-12-build-the-chrome-extension)
14. [Install the Chrome Extension](#step-13-install-the-chrome-extension)
15. [Connect the Extension](#step-14-connect-the-extension)
16. [Set Up Your Job Preferences](#step-15-set-up-your-job-preferences)
17. [Log Into LinkedIn](#step-16-log-into-linkedin)
18. [You're Done!](#step-17-youre-done)

---

## Step 0: What You're About to Do

Here's the big picture of what we're setting up:

**Programs you'll install** (all free):
- **Git** — downloads code from the internet
- **Docker Desktop** — runs the job-finding tool in an isolated "container"
- **Node.js** — builds the Chrome extension (one-time use)
- **Python** — runs one setup script for Gmail (one-time use)

**Accounts you'll create** (all free except Claude):
- **Anthropic** — the company that makes Claude AI ($1-5/month)
- **Google Cloud** — lets the tool send you text messages via Gmail
- **Google Apps Script** — lets the tool read/edit your resume

**Things you already have:**
- A Google/Gmail account
- A LinkedIn account
- Google Chrome browser

**How long will this take?**
About 30–60 minutes, depending on download speeds. Most of that is waiting for things to install.

---

## Key Concepts (Read This First)

### What is a "Terminal"?

A terminal is a window where you type commands to your computer instead of clicking buttons. On Windows, it's called **Command Prompt** or **PowerShell**.

**How to open it:**
1. Press the **Windows key** on your keyboard (the flag icon, bottom-left)
2. Type `cmd`
3. Click **Command Prompt**

A black window appears with blinking cursor. That's your terminal. You type commands here and press Enter to run them.

### What is Docker?

Imagine you could put an entire mini-computer inside your computer — with its own programs, files, and settings — that doesn't affect anything else on your machine. That's what Docker does. It creates "containers" — isolated environments where programs run.

**Why?** Because this tool needs specific versions of specific programs. Instead of installing all of them on your computer (and potentially breaking other things), Docker bundles everything into one neat container.

**Docker Desktop** is the app you install to make this work on Windows.

### What is "Virtualization"?

Virtualization is a feature built into your computer's processor (CPU) that allows it to pretend to be multiple computers at once. Docker needs this feature turned on.

**Good news:** On most modern computers, it's already enabled. If it's not, we'll show you how to turn it on.

### What is an API Key?

When one program needs to talk to another program over the internet, it often needs a "key" — like a password — to prove it has permission. You'll create a few of these. They look like long random strings of letters and numbers.

### What is OAuth?

When you want to let an app access your Gmail (to send texts for you), Google doesn't want you to give the app your password. Instead, Google shows you a screen that says "This app wants to send emails on your behalf — Allow?" That process is called OAuth. You'll do this once.

---

## Step 1: Install Git

**What is Git?** A program that downloads code projects from the internet and keeps track of changes. We need it to download this project.

### Instructions:

1. Open your web browser and go to: [git-scm.com/downloads](https://git-scm.com/downloads)
2. Click **Windows**
3. The download should start automatically. If it doesn't, click the link for "64-bit Git for Windows Setup"
4. Find the downloaded file (usually in your Downloads folder) and double-click it
5. An installer window appears. **Just keep clicking "Next" for every screen.** The default options are all fine.
6. On the last screen, click **Install**
7. When it says "Completing the Git Setup Wizard," click **Finish**

### Verify It Worked:

1. Open a terminal (Windows key → type `cmd` → click Command Prompt)
2. Type this and press Enter:
   ```
   git --version
   ```
3. You should see something like: `git version 2.44.0.windows.1`

**If you see an error:** Close the terminal, open a new one, and try again. Sometimes Windows needs a fresh terminal to recognize newly installed programs.

> **Kiro:** Say "Check if Git is installed" and Kiro will run the verification for you.

---

## Step 2: Download This Project

Now we'll use Git to download all the code for this tool.

### Instructions:

1. Open a terminal (if you don't have one open already)
2. Decide where you want the project to live. Your Documents folder is fine. Type:
   ```
   cd %USERPROFILE%\Documents
   ```
   (This navigates to your Documents folder)
3. Download the project:
   ```
   git clone https://github.com/derek832/job-application-tool.git
   ```
4. Go into the project folder:
   ```
   cd job-application-tool
   ```

You now have all the code on your computer. You can see the folder in File Explorer at `Documents\job-application-tool`.

> **Kiro:** Say "Clone the repo" and Kiro will handle this.

---

## Step 3: Install Docker Desktop

**What is Docker Desktop?** The app that lets your computer run "containers" — isolated mini-environments. This is the most important install because the entire tool runs inside a Docker container.

### Instructions:

1. Go to: [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. Click **Download for Windows**
3. Run the downloaded installer (`Docker Desktop Installer.exe`)
4. The installer will show some options:
   - **"Use WSL 2 instead of Hyper-V"** — Leave this **checked** ✓
   - **"Add shortcut to desktop"** — Your choice
5. Click **Ok** and wait for installation (this takes a few minutes)
6. When it says "Installation succeeded," click **Close and restart** (your computer will restart)

### After Restart:

1. Docker Desktop should open automatically. If not, find it in your Start menu and open it
2. It may ask you to accept a license agreement — click **Accept**
3. It may ask you to create a Docker Hub account — you can **skip this** or create a free one
4. Wait until you see the Docker Desktop window with a green "Running" indicator (bottom-left area)

### Verify It Worked:

Open a new terminal and type:
```
docker --version
```
You should see something like: `Docker version 26.1.0, build ...`

Then type:
```
docker compose version
```
You should see something like: `Docker Compose version v2.27.0`

### If Something Goes Wrong:

**"Hardware assisted virtualization and data execution protection must be enabled"**

This means your computer's virtualization feature is turned off. Here's how to turn it on:

1. You need to enter your computer's BIOS/UEFI settings (the settings that control your hardware)
2. Restart your computer
3. As it's starting up (before Windows loads), press the BIOS key repeatedly. This key depends on your computer brand:
   - **Dell:** F2
   - **HP:** F10 or Esc
   - **Lenovo:** F1 or F2
   - **ASUS:** F2 or Del
   - **Acer:** F2 or Del
   - **MSI:** Del
4. In the BIOS menu, look for one of these (it varies by brand):
   - "Intel Virtualization Technology" → set to **Enabled**
   - "Intel VT-x" → set to **Enabled**
   - "AMD-V" or "SVM Mode" → set to **Enabled**
   - It's usually under "Advanced," "CPU Configuration," or "Security"
5. Save and exit (usually F10, then confirm)
6. Your computer will restart. Open Docker Desktop again.

**If you can't find it:** Search YouTube for "enable virtualization [your computer brand and model]" — there are video guides for almost every computer.

**"WSL 2 installation is incomplete"**

1. Go to: [aka.ms/wsl2kernel](https://aka.ms/wsl2kernel)
2. Click the download link for "WSL2 Linux kernel update package for x64 machines"
3. Run the downloaded installer
4. Restart Docker Desktop

> **Kiro:** Say "Check if Docker is running" and Kiro will verify the installation.

---

## Step 4: Install Node.js

**What is Node.js?** A program that runs JavaScript code. We need it to build the Chrome Extension. You'll use it once during setup and then never think about it again.

### Instructions:

1. Go to: [nodejs.org](https://nodejs.org/)
2. Click the big green button that says **LTS** (Long Term Support) — this is the stable version
3. Run the downloaded installer
4. Click through the installer — **accept all defaults** (Next, Next, Next, Install)
5. When it finishes, click **Finish**

### Verify It Worked:

Open a **new** terminal (important — old terminals won't know about the new install) and type:
```
node --version
```
Should show something like: `v20.12.0`

Then:
```
npm --version
```
Should show something like: `10.5.0`

> **Kiro:** Say "Check if Node.js is installed" and Kiro will verify.

---

## Step 5: Install Python

**What is Python?** A programming language. We need it to run one setup script that authorizes the tool to use your Gmail. You won't write any Python — just run one command.

### Instructions:

1. Go to: [python.org/downloads](https://www.python.org/downloads/)
2. Click the big yellow **"Download Python 3.x.x"** button
3. Run the downloaded installer
4. **⚠️ IMPORTANT:** At the bottom of the first installer screen, there's a checkbox that says **"Add python.exe to PATH"** — **CHECK THIS BOX** ✓
5. Then click **"Install Now"** (the top option)
6. Wait for installation to complete
7. Click **Close**

### Verify It Worked:

Open a **new** terminal and type:
```
python --version
```
Should show something like: `Python 3.12.3`

**If it says "python is not recognized":** You probably didn't check the "Add to PATH" box. The easiest fix is to uninstall Python (Settings → Apps → Python → Uninstall) and install it again, this time checking that box.

> **Kiro:** Say "Check if Python is installed" and Kiro will verify.

---

## Step 6: Create Your Settings File

The tool needs some private information to work (your API keys, email address, etc.). These go in a file called `.env` that stays on your computer and is never shared.

### Instructions:

1. Open a terminal and make sure you're in the project folder:
   ```
   cd %USERPROFILE%\Documents\job-application-tool
   ```
2. Create your settings file by copying the template:
   ```
   copy .env.example .env
   ```

That's it! You now have a `.env` file. We'll fill it in over the next few steps.

**To edit this file:** Right-click `.env` in File Explorer → Open with → Notepad (or any text editor). You'll see lines like `CLAUDE_API_KEY=` — you'll paste values after the `=` sign.

> **Kiro:** Say "Create the .env file" and Kiro will do this for you.

---

## Step 7: Get a Claude AI Key

**What is Claude?** An AI made by a company called Anthropic. This tool uses Claude to read job descriptions and decide if they match what you're looking for. It's the only paid part — typically $1–5 per month.

### Instructions:

1. Go to: [console.anthropic.com](https://console.anthropic.com/)
2. Click **Sign up** and create an account (email + password)
3. You'll need to add a payment method:
   - Click **Settings** (or the gear icon) in the left sidebar
   - Click **Billing** → **Add payment method**
   - Add a credit/debit card
   - You can set a monthly spending limit (e.g., $10) so you never get surprised
4. Now get your API key:
   - Click **API Keys** in the left sidebar
   - Click **Create Key**
   - Give it a name (anything — like "Job Tool")
   - Click **Create Key**
   - **IMPORTANT:** Copy the key immediately! It starts with `sk-ant-...` and you won't be able to see it again after you close this page
5. Open your `.env` file in Notepad and paste the key:
   ```
   CLAUDE_API_KEY=sk-ant-your-key-here
   ```
6. Save the file (Ctrl+S)

> **Kiro:** Say "I have my Claude API key: sk-ant-..." and Kiro will add it to your .env file for you. (Don't worry — Kiro keeps your keys private.)

---

## Step 8: Set Up Google Apps Script

**What is this for?** The tool needs to read your resume (from Google Docs), customize it for each job, and export it as a PDF to attach to applications. Google Apps Script is a free Google service that makes this possible.

### Step 8a: Prepare Your Resume

1. Open [docs.google.com](https://docs.google.com)
2. Either open your existing resume or create a new document with your resume content
3. Look at the URL in your browser's address bar. It looks like this:
   ```
   https://docs.google.com/document/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ123/edit
   ```
4. The long string of letters and numbers between `/d/` and `/edit` is your **Document ID**
5. Select it and copy it (Ctrl+C). You'll need it in a moment.

### Step 8b: Create the Script

1. Open a new browser tab and go to: [script.google.com](https://script.google.com)
2. Click **New project** (top-left)
3. You'll see a code editor with some text that says `function myFunction() { }`
4. **Select all the text** in the editor (Ctrl+A) and **delete it**
5. Now you need to paste in the code from this project:
   - On your computer, navigate to the project folder → `gas` folder → open `Code.gs` with Notepad
   - Select all (Ctrl+A), copy (Ctrl+C)
   - Go back to the Apps Script editor and paste (Ctrl+V)
6. Click the **floppy disk icon** (💾) to save, or press Ctrl+S
7. Click "Untitled project" at the top and rename it to "Job Application Tool"

### Step 8c: Add Your Document ID

1. In the Apps Script editor, look at the left sidebar
2. Click the **gear icon** (⚙️) — this opens Project Settings
3. Scroll down until you see **Script Properties**
4. Click **Add script property**
5. In the "Property" field, type: `DOCUMENT_ID`
6. In the "Value" field, paste your Document ID from Step 8a
7. Click the blue **Save script properties** button

### Step 8d: Deploy the Script

1. Click the blue **Deploy** button (top-right of the editor)
2. Click **New deployment**
3. Next to "Select type," click the **gear icon** (⚙️) → select **Web app**
4. Fill in:
   - **Description:** `Resume API` (or anything you want)
   - **Execute as:** `Me`
   - **Who has access:** `Only myself`
5. Click **Deploy**
6. Google will ask you to authorize:
   - Click **Authorize access**
   - Choose your Google account
   - You might see "Google hasn't verified this app" — click **Advanced** → **Go to Job Application Tool (unsafe)**
   - Click **Allow**
7. You'll see a **Web app URL** — it looks like `https://script.google.com/macros/s/long-string/exec`
8. Click the **copy icon** next to the URL to copy it
9. Open your `.env` file and paste it:
   ```
   GOOGLE_APPS_SCRIPT_URL=https://script.google.com/macros/s/your-long-string/exec
   ```
10. Save the file

> **Kiro:** Say "I've deployed the Apps Script, here's the URL: [paste URL]" and Kiro will update your .env file.

---

## Step 9: Set Up Gmail Notifications

**What is this for?** The tool sends you text messages when it needs your attention (like reviewing a borderline job). It does this by sending an email to your phone carrier's email-to-SMS gateway. For example, if your number is 555-123-4567 and you're on T-Mobile, it emails `5551234567@tmomail.net` and that arrives as a text.

This step gives the tool permission to send emails from your Gmail account.

### Step 9a: Create a Google Cloud Project

1. Go to: [console.cloud.google.com](https://console.cloud.google.com)
2. If this is your first time, agree to the Terms of Service and click **Agree and Continue**
3. At the very top of the page, you'll see a project dropdown (it might say "Select a project" or show a project name). Click it.
4. In the popup, click **NEW PROJECT** (top-right of the popup)
5. Name it: `Job App Tool` (or anything)
6. Click **Create**
7. Wait a moment, then click the project dropdown again and select your new project

### Step 9b: Enable the Gmail API

1. In the left sidebar, click **APIs & Services** → **Library**
   (If you don't see the sidebar, click the hamburger menu ☰ at the top-left)
2. In the search box, type: `Gmail API`
3. Click **Gmail API** in the results
4. Click the blue **Enable** button
5. Wait for it to enable (a few seconds)

### Step 9c: Set Up the OAuth Consent Screen

1. In the left sidebar, go to **APIs & Services** → **OAuth consent screen**
2. Select **External** and click **Create**
3. Fill in:
   - **App name:** `Job Application Tool` (or anything)
   - **User support email:** select your email from the dropdown
   - **Developer contact information:** type your email address
4. Click **Save and Continue**
5. On the "Scopes" page — just click **Save and Continue** (don't add anything)
6. On the "Test users" page — click **Add Users**, type your own email address, click **Add**, then **Save and Continue**
7. Click **Back to Dashboard**

### Step 9d: Create OAuth Credentials

1. In the left sidebar, go to **APIs & Services** → **Credentials**
2. Click **+ CREATE CREDENTIALS** (top of the page) → **OAuth client ID**
3. Set:
   - **Application type:** `Desktop app`
   - **Name:** `Job Application Tool` (or anything)
4. Click **Create**
5. A popup appears showing your client ID and secret. Click **DOWNLOAD JSON** (the download arrow icon)
6. A file downloads (named something like `client_secret_123...json`)
7. **Move this file** to the project folder:
   - Open File Explorer
   - Navigate to: `Documents\job-application-tool\automator\data\`
   - Move (or copy) the downloaded JSON file here
   - **Rename it** to exactly: `gmail_credentials.json`

### Step 9e: Authorize the Tool

Now we run a script that opens a browser window where you'll give the tool permission to send emails.

1. Open a terminal
2. Navigate to the automator folder:
   ```
   cd %USERPROFILE%\Documents\job-application-tool\automator
   ```
3. Install the required Python packages:
   ```
   pip install google-auth google-auth-oauthlib google-api-python-client
   ```
4. Run the authorization script:
   ```
   python authorize_gmail.py
   ```
5. A browser window opens:
   - Sign in with your Gmail account
   - You'll see "Google hasn't verified this app" — click **Advanced** → **Go to Job Application Tool (unsafe)**
   - Click **Allow** (grant permission to send emails)
   - You'll see "The authentication flow has completed" or similar
6. Back in the terminal, you should see a success message
7. A new file `gmail_token.json` now exists in the `automator/data/` folder

### Step 9f: Set Your Gmail Address

Open your `.env` file and add your Gmail address:
```
GMAIL_USER=your.email@gmail.com
```
Save the file.

> **Kiro:** Say "Run the Gmail authorization" and Kiro will execute the commands. You'll still need to click through the browser authorization yourself.

---

## Step 10: Build and Start the Tool

Everything is configured. Now we build the Docker container and start it.

### Instructions:

1. Open a terminal
2. Navigate to the project folder:
   ```
   cd %USERPROFILE%\Documents\job-application-tool
   ```
3. Make sure Docker Desktop is running (check for the whale icon in your system tray, bottom-right of your screen. If it's not there, open Docker Desktop from the Start menu and wait for it to show "Running")
4. Build the container (this downloads and installs everything the tool needs — takes 3-10 minutes the first time):
   ```
   docker compose build automator
   ```
   You'll see lots of text scrolling by. This is normal. Wait until you see "Successfully built" or it returns to the command prompt.
5. Start the tool:
   ```
   docker compose up -d
   ```
   The `-d` means "run in the background" — the tool keeps running even after you close the terminal.

### Verify It's Running:

```
docker compose logs automator
```

You should see lines mentioning:
- `Uvicorn running on http://127.0.0.1:7432`
- `Application startup complete`

If you see error messages instead, read them carefully. The most common issues:
- "CLAUDE_API_KEY not set" → your `.env` file is missing the Claude key
- "No such file or directory" → make sure you're in the `job-application-tool` folder
- Docker errors → make sure Docker Desktop is running

> **Kiro:** Say "Build and start the Docker container" and Kiro will run both commands and check the logs for you.

---

## Step 11: Get Your API Token

When the tool starts for the first time, it creates a secret "token" — a long random string that the Chrome Extension uses to prove it's allowed to talk to the tool. Think of it like a password between the extension and the server.

### Instructions:

1. In your terminal (in the project folder), run:
   ```
   docker compose logs automator | findstr "API_TOKEN"
   ```
2. You'll see a line containing your token — a long string of letters and numbers
3. **Copy this token** — you'll paste it into the Chrome Extension in a few steps

If you don't see it, try:
```
docker compose logs automator
```
And look for a line mentioning "API_TOKEN" or "Generated API token."

> **Kiro:** Say "Show me the API token" and Kiro will find it in the logs for you.

---

## Step 12: Build the Chrome Extension

The Chrome Extension is your control panel — it's how you interact with the tool. We need to "build" it (convert the source code into something Chrome can use).

### Instructions:

1. Open a terminal
2. Navigate to the extension folder:
   ```
   cd %USERPROFILE%\Documents\job-application-tool\extension
   ```
3. Install the extension's dependencies (the libraries it needs):
   ```
   npm ci
   ```
   This downloads packages and takes about 30-60 seconds. You'll see a progress bar.
4. Build the extension:
   ```
   npm run build
   ```
   This compiles everything into a `dist` folder. It should take about 10-20 seconds.

If either command shows errors:
- Make sure Node.js is installed (Step 4)
- Try closing and reopening your terminal
- Make sure you're in the `extension` folder

> **Kiro:** Say "Build the Chrome extension" and Kiro will run both commands.

---

## Step 13: Install the Chrome Extension

Now we load the built extension into Chrome.

### Instructions:

1. Open **Google Chrome**
2. In the address bar, type: `chrome://extensions` and press Enter
3. In the top-right corner, turn on **Developer mode** (flip the toggle switch)
4. Three new buttons appear at the top. Click **Load unpacked**
5. A folder picker opens. Navigate to:
   ```
   Documents → job-application-tool → extension → dist
   ```
6. Select the `dist` folder and click **Select Folder**
7. The extension should now appear in the list on the page
8. Look at your Chrome toolbar (top-right, next to the address bar). You might see the extension icon, or you might need to:
   - Click the **puzzle piece icon** (🧩) in the toolbar
   - Find "Job Application Tool" in the list
   - Click the **pin icon** (📌) next to it to keep it visible

---

## Step 14: Connect the Extension

Now we tell the extension how to talk to the tool running in Docker.

### Instructions:

1. Click the **extension icon** in your Chrome toolbar
2. The extension popup opens. Look for a **Settings** tab or gear icon (⚙️)
3. Click it
4. You'll see a field for **API Token** (or "Bearer Token" or similar)
5. Paste the token you copied in Step 11
6. Click **Save** (or it may save automatically)
7. The connection status should change to **"Connected"** (green)

**If it says "Disconnected" or "Error":**
- Make sure Docker is running: open a terminal and run `docker compose up -d`
- Make sure the token is correct (no extra spaces before or after)
- Try refreshing the extension: go to `chrome://extensions`, find the extension, click the refresh icon (🔄)

---

## Step 15: Set Up Your Job Preferences

Now the fun part — tell the tool what you're looking for!

### Instructions:

1. Click the extension icon to open it
2. You'll see several configuration sections. Fill in each one:

**Search Config** (what jobs to look for):
- **Keywords:** Job titles or skills to search for (e.g., "software engineer", "product manager", "data analyst")
- **Location:** Where you want to work (e.g., "San Francisco, CA" or "Remote")
- **Job type:** Full-time, part-time, contract, etc.
- **Experience level:** Entry, mid, senior, etc.
- **Remote preference:** On-site, remote, hybrid

**Goals Profile** (what makes a job "good" for you):
- **Target titles:** The job titles you actually want
- **Target industries:** Industries you're interested in
- **Salary range:** Your minimum and ideal salary
- **Deal-breakers:** Things that automatically disqualify a job (e.g., "requires 10+ years experience", "must relocate to Alaska")
- **Priorities:** What matters most to you (growth, compensation, work-life balance, etc.)

**Your Profile** (info needed for applications):
- **Full name**
- **Email address**
- **Phone number**
- **Work authorization** (e.g., "US Citizen", "Authorized to work in the US")
- **Common answers:** Years of experience, highest education, etc.

**SMS Settings** (for text notifications):
- **Phone number:** Your 10-digit number (no dashes)
- **Carrier gateway:** Your carrier's email-to-SMS address:
  - T-Mobile: `@tmomail.net`
  - AT&T: `@txt.att.net`
  - Verizon: `@vtext.com`
  - Sprint: `@messaging.sprintpcs.com`
  - Google Fi: `@msg.fi.google.com`

---

## Step 16: Log Into LinkedIn

The tool browses LinkedIn using a real browser (just like you would). It needs you to log in once so it can save your session.

### Instructions:

1. In the extension, go to the **Dashboard**
2. Click **Run Now** (or "Manual Run" or similar)
3. The tool will start trying to browse LinkedIn
4. If LinkedIn requires login (it will the first time), the tool will pause
5. A browser window may appear (this is the Playwright browser) — log into LinkedIn normally
6. Once logged in, the tool saves your session cookies and won't ask again for a while

**Note:** LinkedIn sessions expire after a few weeks. If the tool stops finding jobs, you may need to log in again by triggering another manual run.

---

## Step 17: You're Done!

🎉 **Congratulations!** The tool is now set up and running.

### What Happens Now:

- **Every weekday** (Monday–Friday), the tool automatically searches LinkedIn, scores jobs, and applies to good fits
- **You'll get text messages** when something needs your attention
- **Check the extension** whenever you want to see what's happening, review queued jobs, or adjust settings

### Day-to-Day Usage:

- **Just leave Docker Desktop running.** The tool runs in the background automatically.
- **Check the extension** when you get a text notification
- **Review the Human Queue** to approve or skip borderline jobs
- **Adjust your settings** as you learn what works (maybe you want to raise/lower the fit threshold, add new keywords, etc.)

### Stopping the Tool:

If you want to pause job searching (maybe you got a job! 🎉):
```
docker compose down
```

To start it again later:
```
docker compose up -d
```

---

## Troubleshooting Reference

| Problem | Solution |
|---------|----------|
| Extension shows "Disconnected" | Make sure Docker Desktop is open and running. Run `docker compose up -d` in the project folder. |
| "Unauthorized" errors | The API token doesn't match. Run `docker compose logs automator | findstr "API_TOKEN"` to get the correct token and re-paste it in extension settings. |
| Text notifications not arriving | The Gmail token may have expired. Run `cd automator` then `python authorize_gmail.py` again. |
| Google Docs errors | Re-deploy the Apps Script (Step 8d) and update the URL in settings. |
| LinkedIn login required | Trigger a manual run from the extension and log in when prompted. |
| Docker build fails | Make sure Docker Desktop is running (green whale icon in system tray). Make sure you have internet. |
| "Virtualization not enabled" | See the detailed instructions in Step 3 about enabling virtualization in BIOS. |
| "WSL 2 incomplete" | Visit [aka.ms/wsl2kernel](https://aka.ms/wsl2kernel) and install the update. |
| `npm ci` fails | Make sure Node.js is installed (Step 4). Open a new terminal and try again. |
| `python` not recognized | Reinstall Python (Step 5) and make sure "Add to PATH" is checked. Open a new terminal. |
| `docker` not recognized | Make sure Docker Desktop is installed and running. Open a new terminal. |
| Build takes forever | First build downloads ~1GB of data. Make sure you have good internet. Subsequent builds are much faster. |
| "Port 7432 already in use" | Something else is using that port. Run `docker compose down` first, then `docker compose up -d`. |
| Extension not showing in Chrome | Make sure you loaded the `dist` folder (not `extension` or `src`). Check Developer mode is on. |

---

## Getting Help

If you're stuck on any step:

1. **Using Kiro:** Just describe what's happening. Paste any error messages. Kiro can diagnose most issues.
2. **Common pattern:** If something "isn't recognized" after installing it, close your terminal and open a new one. Windows needs a fresh terminal to see new programs.
3. **Docker issues:** 90% of Docker problems are solved by: (1) making sure Docker Desktop is open and showing "Running", and (2) restarting Docker Desktop.

---

## What Each File Does (Reference)

If you're curious about what's in this project:

| File/Folder | What It Is |
|-------------|-----------|
| `automator/` | The brain of the tool — Python code that does all the work |
| `automator/src/pipeline/` | The step-by-step process: find jobs → score them → apply |
| `automator/src/agents/` | The AI part — talks to Claude to understand job descriptions |
| `automator/src/integrations/` | Connections to Gmail, Google Docs, LinkedIn |
| `automator/data/` | Your private credentials and the database (never shared) |
| `extension/` | The Chrome Extension — your control panel |
| `extension/dist/` | The built extension (this is what Chrome loads) |
| `gas/Code.gs` | The Google Apps Script code for resume management |
| `docker-compose.yml` | Instructions telling Docker how to run the container |
| `.env` | Your private settings (API keys, email) — never shared |
| `.env.example` | A template showing what settings are needed |
