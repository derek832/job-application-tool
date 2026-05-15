---
inclusion: always
---

# Development Workflow

## Project Structure

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
├── extension/                  # Chrome Extension (TypeScript + React)
│   ├── src/
│   │   ├── api/                # Typed Automator API client
│   │   ├── components/         # React components
│   │   ├── pages/              # Extension views (popup, options)
│   │   └── types/              # Zod schemas + inferred types
│   ├── public/
│   │   └── manifest.json
│   ├── package.json
│   └── tsconfig.json
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
2. Build the automator image: `docker compose build automator`
3. Start the stack: `docker compose up -d`
4. Check startup health: `docker compose logs automator --follow`
5. Load the extension in Chrome: open `chrome://extensions`, enable Developer Mode, click "Load unpacked", select `extension/dist/`.

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

### TypeScript (Extension) Setup

```bash
cd extension
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
| Build extension | `npm run build` | `extension/` |
| Type-check extension | `npm run typecheck` | `extension/` |
| Lint extension | `npm run lint` | `extension/` |
| Run CVE audit (Python) | `pip-audit --requirement requirements.txt` | `automator/` |
| Run CVE audit (Node) | `npm audit --audit-level=moderate` | `extension/` |

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

- **automator** — the FastAPI service, bound to `127.0.0.1:7432`
- **volume: app-data** — mounted at `/app/data` inside the container; holds `state.db`, PDFs, logs, and backups

Environment variables required in `.env`:

```
CLAUDE_API_KEY=
GMAIL_USER=
GMAIL_APP_PASSWORD=
GOOGLE_APPS_SCRIPT_URL=
API_TOKEN=                      # Leave blank on first run; auto-generated
DATA_DIR=./data                 # Host path for the mounted volume
```

## Google Apps Script Deployment

The `gas/Code.gs` script must be deployed as a Web App in Google Apps Script:

1. Open [script.google.com](https://script.google.com), create a new project.
2. Paste the contents of `gas/Code.gs`.
3. Deploy → New deployment → Web App → Execute as: Me → Who has access: Only myself.
4. Copy the deployment URL into `.env` as `GOOGLE_APPS_SCRIPT_URL`.
5. On first run, authorize the script when prompted.

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
