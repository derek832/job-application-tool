---
inclusion: manual
---

# Setup Guide Steering

When the user asks for help setting up the project, follow the complete setup guide at #[[file:SETUP_GUIDE.md]].

## Your Role During Setup

You are walking a non-technical user through setup. Assume they have never used a terminal, never installed developer tools, and don't know what Docker, Git, Python, or Node.js are.

## Approach

1. **Ask which step they're on** (or if they're starting from scratch, begin at Step 1).
2. **Run every command you can** — don't just show them commands, execute them.
3. **Verify each step worked** before moving to the next one (run version checks, check logs, etc.).
4. **Explain browser-based steps clearly** — for things you can't do (like clicking buttons on websites), give them extremely specific instructions with exact button names and locations.
5. **If something fails**, diagnose it immediately. Check common causes. Don't just say "try again."
6. **Keep track of progress** — remember which steps are done so you don't repeat them.

## Commands You Should Run Proactively

- `git --version` — verify Git is installed
- `docker --version` and `docker compose version` — verify Docker
- `node --version` and `npm --version` — verify Node.js
- `python --version` — verify Python
- `copy .env.example .env` — create the env file
- `pip install google-auth google-auth-oauthlib google-api-python-client` — install Gmail auth deps
- `python authorize_gmail.py` — run Gmail auth (in automator/ directory)
- `docker compose build automator` — build the container
- `docker compose up -d` — start the tool
- `docker compose logs automator` — check startup
- `docker compose logs automator | findstr "API_TOKEN"` — find the API token
- `npm ci` — install extension dependencies (in extension/ directory)
- `npm run build` — build the extension (in extension/ directory)

## Things You Cannot Do (User Must Do Manually)

- Create accounts (Anthropic, Google Cloud)
- Click through OAuth consent screens in the browser
- Load the extension into Chrome (chrome://extensions)
- Configure extension settings (paste token, set preferences)
- Log into LinkedIn through the Playwright browser
- Enable virtualization in BIOS
- Install Docker Desktop, Node.js, Python, Git (you can verify after they install)

## Error Handling

- If `docker` is not recognized → Docker Desktop isn't installed or isn't running
- If `python` is not recognized → Python wasn't added to PATH during install
- If `npm` is not recognized → Node.js isn't installed or terminal needs to be reopened
- If Docker build fails with "virtualization" → they need to enable VT-x/AMD-V in BIOS
- If Docker build fails with "WSL" → they need the WSL 2 kernel update from aka.ms/wsl2kernel
- If `docker compose up` fails with port conflict → run `docker compose down` first
- If Gmail auth fails → credentials file is missing or misnamed
