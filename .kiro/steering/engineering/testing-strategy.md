---
inclusion: manual
---

# Engineering — Testing Strategy

## Philosophy

Tests exist to catch regressions and validate behavior at boundaries. For this project, the highest-value tests are:

1. **State machine transitions** — Does a job move to the correct status given specific inputs?
2. **Scoring boundary logic** — Does a score of 69 get skipped while 70 gets queued?
3. **Pre-filter accuracy** — Do the keyword and salary filters correctly eliminate non-matches?
4. **Data integrity** — Are audit trails written? Are timestamps set? Is deduplication working?

Low-value tests (avoid spending time on these):
- Testing that FastAPI returns 200 for a valid request (framework behavior)
- Testing that SQLAlchemy can insert and read a row (ORM behavior)
- Testing mock interactions that don't validate real logic

## Test Organization

```
tests/
├── unit/              # Pure logic, no I/O, no database
│   ├── test_fit_classifier.py
│   ├── test_properties.py
│   └── ...
├── integration/       # Real in-memory SQLite, mocked external APIs
│   └── ...
└── conftest.py        # Shared fixtures
```

## What to Mock, What to Use Real

| Component | In Unit Tests | In Integration Tests |
|-----------|--------------|---------------------|
| SQLite database | Mock the session | Real in-memory DB |
| Claude API | Always mock | Always mock |
| Gmail / SMS | Always mock | Always mock |
| Google Docs | Always mock | Always mock |
| Playwright / browser | Always mock | Always mock |
| Pydantic models | Real | Real |
| Fit classifier logic | Real | Real |
| Job repo functions | Mock in unit, real in integration | Real |

**Rule:** Never let a test make a real network call. Not to Claude, not to LinkedIn, not to Gmail. Tests must run offline and in < 30 seconds total.

## Property-Based Tests

The project uses Hypothesis for property-based testing (`test_properties.py`). These are high-value because they find edge cases humans miss:

- Score boundary classification across all possible score values
- SMS message composition never exceeds length limits
- URL construction produces valid URLs for any search config
- Status transitions only accept valid status strings
- Pydantic schemas reject malformed input

**When to add a property test:** When a function has a clear contract (input domain → output invariant) and the edge cases aren't obvious. Scoring classification, text formatting, and validation are good candidates.

## Testing Scoring and Prompts

Scoring is the most important logic in the system. Test it at multiple levels:

1. **Unit: classifier logic** — Given a score and thresholds, does `classify_fit` return the right category? Does `is_threshold_boundary` detect margins correctly? These are pure functions — test exhaustively.

2. **Unit: scoring stage routing** — Given a `FitScoreResult` (mocked Claude response), does `run_scoring` set the correct status, queue_reason, and trigger the right notification? Mock the Claude client, use a real session.

3. **Do NOT unit-test the prompt text itself.** Prompts are iterated on empirically. Testing that a prompt contains specific words is brittle and adds no value.

4. **Evaluation over testing for prompt quality.** When changing a scoring prompt, validate against a set of known jobs with expected scores (manual spot-check), not automated assertions.

## Testing Playwright / Browser Automation

Browser automation is inherently flaky. Design tests accordingly:

- **Don't test Playwright interactions in unit tests.** Mock the page object entirely.
- **Integration tests for browser code** should validate the logic (what gets clicked, what gets typed) not the browser behavior.
- **Real browser testing is manual.** Use `dry_run=true` mode and watch it work. No automated Playwright test suite — the maintenance cost exceeds the value for a single-user tool.

## Test Fixtures

Common fixtures in `conftest.py`:

- `sample_job_record` — A `JobRecord` in `discovered` status with realistic data
- `async_session` — In-memory SQLite async session with tables created
- `sms_settings` — Valid `SMSSettings` for notification tests
- `user_profile` / `goals_profile` / `search_config` — Validated Pydantic models with realistic data

**Rule:** Fixtures should represent realistic data, not minimal stubs. A `JobRecord` fixture should have a real-looking job title, company, and description — not "test_title" and "test_company". This catches bugs where code assumes certain string patterns.

## Coverage Targets

- Core pipeline logic (`pipeline/`, `agents/`, `db/`): 80%+ line coverage
- API routes: 60%+ (mostly happy-path validation)
- Integration tests: Focus on the full scoring→routing→notification flow

Coverage is a floor, not a goal. 100% coverage with bad assertions is worse than 70% coverage with meaningful tests.

## When to Write Tests

- **Before fixing a bug:** Write a test that reproduces the bug first, then fix it.
- **Alongside new pipeline logic:** Scoring, classification, and state transitions get tests immediately.
- **After stabilizing a feature:** Browser automation and external integrations get tests once the approach is proven (not during rapid iteration).
- **Never retroactively for stable code:** If code has been working in production for weeks without issues, don't write tests just for coverage numbers.
