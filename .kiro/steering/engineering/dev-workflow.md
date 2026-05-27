---
inclusion: manual
---

# Engineering — Development Workflow

## Project Structure

> **Note:** Wave 0 replaces `extension/` with `webapp/`. The structure below shows the post-Wave-0 target. Until Wave 0 is complete, `extension/` still exists and `webapp/` does not.

```
job-application-tool/
├── automator/                  # Python FastAPI backend (runs in Docker)
│   ├── src/
│   │   ├── api/                # FastAPI route handlers
│   │   ├── pipeline/           # Job pipeline stages
│   │   ├── agents/             # Vision agent, Claude client
│   │   ├── integrations/       # Gmail, Google Docs, LinkedIn clients
│   │   ├── db/                 # SQLAlchemy models, migrations
│   │   ├── scheduler/          # APScheduler setup
│   │   ├── exceptions.py       # All custom exception classes
│   │   └── main.py             # FastAPI app entrypoint
│   ├── tests/
│   ├── requirements.in         # Direct dependencies (human-edited)
│   ├── requirements.txt        # Pinned full dependency tree (pip-compile output)
│   └── Dockerfile
├── webapp/                     # React SPA (TypeScript + Tailwind, served by nginx)
│   ├── src/
│   │   ├── api/                # Typed Automator API client (relative /api/ paths)
│   │   ├── components/         # React components
│   │   ├── hooks/              # usePolling, useBadge, etc.
│   │   ├── pages/              # App views (Dashboard, Queue, History, etc.)
│   │   └── types/              # Zod schemas + inferred types
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── nginx.conf
│   └── Dockerfile              # Multi-stage: Node build → nginx serve
├── gas/                        # Google Apps Script source
│   └── Code.gs
├── docker-compose.yml
├── .env.example                # Template — never commit .env
├── SECURITY_NOTES.md           # CVE acceptance log
└── .kiro/
    ├── specs/
    └── steering/
```

## Environment Setup

### First-Time Setup

1. Copy `.env.example` to `.env` and fill in all values.
2. Build the stack: `docker compose build`
3. Start the stack: `docker compose up -d`
4. Check startup health: `docker compose logs automator --follow`
5. Open `http://127.0.0.1:3000` in your browser to access the web app.

### Python (Automator) Setup for Local Development

```bash
cd automator
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install pip-tools
pip-sync requirements.txt       # Install exact pinned versions
```

To add a new dependency:
1. Add it to `requirements.in`
2. Run `pip-compile requirements.in --output-file requirements.txt`
3. Run `pip-audit --requirement requirements.txt` — fix any HIGH/CRITICAL CVEs before proceeding
4. Run `pip-sync requirements.txt`

### TypeScript (Web App) Setup

```bash
cd webapp
npm ci                          # Always use ci, not install
npm run build                   # Production build to dist/
npm run dev                     # Watch mode for development
```

To add a new dependency:
1. Run `npm install --save-exact <package>` (exact version, no caret)
2. Run `npm audit --audit-level=moderate` — fix any issues before proceeding
3. Commit both `package.json` and `package-lock.json`

## Build Commands

| Task | Command | Working Directory |
|---|---|---|
| Build automator image | `docker compose build automator` | root |
| Start full stack | `docker compose up -d` | root |
| Stop stack | `docker compose down` | root |
| View automator logs | `docker compose logs automator -f` | root |
| Run Python tests | `docker compose run --rm automator pytest` | root |
| Run Python tests (local) | `pytest` | `automator/` |
| Run linter | `ruff check src/` | `automator/` |
| Run formatter check | `black --check src/` | `automator/` |
| Build extension | `npm run build` | `webapp/` |
| Type-check extension | `npm run typecheck` | `webapp/` |
| Lint extension | `npm run lint` | `webapp/` |
| Run CVE audit (Python) | `pip-audit --requirement requirements.txt` | `automator/` |
| Run CVE audit (Node) | `npm audit --audit-level=moderate` | `webapp/` |

## Git Branching Workflow

The repository lives at `https://github.com/derek832/job-application-tool` (private).

### Branch Strategy

- **`main`** — stable, always deployable. Direct commits are forbidden.
- **`feat/<task-id>-<short-description>`** — one branch per spec task (e.g. `feat/1-scaffolding`, `feat/2.1-db-models`).
- **`fix/<short-description>`** — for bug fixes not tied to a spec task.

### Workflow for Each Task

```bash
# 1. Start from latest main
git checkout main
git pull origin main

# 2. Create a feature branch
git checkout -b feat/<task-id>-<short-description>

# 3. Do the work, commit in logical chunks
git add <specific files>
git commit -m "feat: <description>"

# 4. Push and open a PR
git push -u origin feat/<task-id>-<short-description>
gh pr create --title "<title>" --body "<description>" --base main

# 5. Merge via GitHub (squash merge preferred for clean history)
gh pr merge --squash
```

### Commit Message Format

Follow Conventional Commits:
- `feat:` — new feature or spec task implementation
- `fix:` — bug fix
- `refactor:` — code change with no behavior change
- `test:` — adding or updating tests
- `docs:` — documentation only
- `chore:` — build, config, dependency updates

### Rules

- Never commit directly to `main`.
- Each PR should correspond to one spec task or a logical subset of one.
- All pre-commit checks must pass before opening a PR (see checklist below).
- PR titles stay under 70 characters; use the description for details.

---

## Pre-Commit Checklist

Before committing any change, verify all of the following pass:

- [ ] `ruff check src/` — zero warnings
- [ ] `black --check src/` — zero formatting issues
- [ ] `pytest --tb=short` — all tests pass
- [ ] `pip-audit --requirement requirements.txt` — no HIGH/CRITICAL CVEs
- [ ] `npm run typecheck` — zero TypeScript errors
- [ ] `npm run lint` — zero ESLint warnings
- [ ] `npm audit --audit-level=moderate` — no moderate+ CVEs
- [ ] No `.env`, `*.db`, or `*.pdf` files staged for commit
- [ ] Update `TODO.md` — mark completed features as done, move to Completed section

## Testing Approach

### Running Tests

```bash
# All tests
pytest

# With coverage report
pytest --cov=src --cov-report=term-missing

# Single file
pytest tests/test_job_pipeline.py

# Single test
pytest tests/test_job_pipeline.py::test_fit_score_boundary_escalation
```

### Test Organization

- Unit tests: `tests/unit/` — pure logic, no I/O, no mocks needed
- Integration tests: `tests/integration/` — real SQLite in-memory DB, mocked external APIs
- All external service calls (Claude, Gmail, Google Docs, Playwright) are mocked using `pytest-mock` or `respx` (for httpx)
- Fixtures for common objects (Job_Record, Goals_Profile, Search_Config) live in `tests/conftest.py`

## Docker Compose Overview

The `docker-compose.yml` defines:

- **automator** — the FastAPI service, internal-only port (not exposed to host)
- **frontend** — nginx serving the React SPA and proxying `/api/*` to the automator, bound to `127.0.0.1:3000`
- **volume: app-data** — mounted at `/app/data` inside the automator container; holds `state.db`, PDFs, logs, and backups

Environment variables required in `.env`:

```
CLAUDE_API_KEY=
GMAIL_USER=
GOOGLE_APPS_SCRIPT_URL=
API_TOKEN=                      # Leave blank on first run; auto-generated
DATA_DIR=./data                 # Host path for the mounted volume
```

Additionally, the Gmail OAuth2 token file (`data/gmail_token.json`) must be generated once via `python authorize_gmail.py` before the SMS notification feature will work. See the Gmail OAuth2 setup section below.

## Google Apps Script Deployment

The `gas/` directory contains the Google Apps Script source and is configured for deployment via `clasp` (the GAS CLI).

### CLI Deployment (Preferred)

```bash
cd gas
clasp push                    # Push Code.gs to the Apps Script project
clasp deploy -d "description" # Create a new versioned deployment
```

If `clasp push` fails with an auth error, re-authenticate:
```bash
clasp login                   # Opens browser for Google OAuth
clasp push                    # Retry after login
```

The script ID is configured in `gas/.clasp.json`. The `rootDir` is `.` (the `gas/` folder itself), so `clasp push` uploads `Code.gs` and `appsscript.json`.

### Manual Deployment (Fallback)

1. Open [script.google.com](https://script.google.com), open the project.
2. Paste the contents of `gas/Code.gs`.
3. Deploy → New deployment → Web App → Execute as: Me → Who has access: Only myself.
4. Copy the deployment URL into `.env` as `GOOGLE_APPS_SCRIPT_URL`.
5. On first run, authorize the script when prompted.

### When to Deploy

Deploy the GAS script whenever `gas/Code.gs` is modified. This is independent of Docker — no container rebuild needed. The automator calls the deployed web app URL at runtime.

## Updating the Spec

When requirements or design change:
1. Update the relevant section in `.kiro/specs/linkedin-job-automator/requirements.md` or `design.md`.
2. If a new status value, API endpoint, or data model field is added, update `design.md` data models and API tables.
3. Add or update the corresponding unit/integration test before implementing the change.

## Logging and Debugging

- Automator logs are written to `/app/data/logs/automator.log` inside the container (accessible on the host via the mounted volume).
- Log level is controlled by the `LOG_LEVEL` environment variable (default: `INFO`). Set to `DEBUG` for verbose output during development.
- To tail logs live: `docker compose logs automator --follow`
- Playwright traces can be enabled by setting `PLAYWRIGHT_TRACE=1` in `.env`. Traces are saved to `/app/data/traces/` and can be viewed with `playwright show-trace`.
