# Git Workflow — Trunk-Based Development

## Purpose

All code lives on `main`. Commits go directly to main. Docker containers are the test environment. This keeps things simple for a solo developer project.

## The Workflow

### 1. Make Changes

Write code, run tests locally if needed.

### 2. Commit to Main

```
git add <specific files>
git commit -m "type: short description"
```

Commit types: `fix:`, `feat:`, `refactor:`, `test:`, `chore:`

Keep subject under 72 characters. Stage specific files — avoid `git add -A` unless all changes are related.

### 3. Push

```
git push origin main
```

### 4. Deploy

Build and restart the affected service(s):

```
docker compose build automator
docker compose up -d automator
```

Or for frontend changes:
```
docker compose build frontend
docker compose up -d frontend
```

### 5. Verify

For pipeline changes: check logs after the next run.
For frontend changes: refresh the web app.
For test-only changes: run `python -m pytest tests/ -q` — no deploy needed.

## When to Use a Branch

Only when you're genuinely experimenting and want a clean rollback point:
- Risky refactors that touch many files
- Trying an approach you might abandon entirely

In those cases: `git checkout -b experiment/description`, work on it, merge or delete.

## Rules

- **Commit directly to main** for normal work.
- **Always push after committing.** GitHub should have the latest code.
- **Always rebuild after deploy-worthy changes.** Don't leave stale containers.
- **Stage specific files** over `git add -A` to avoid accidentally committing unrelated changes.
- **Flag files that likely contain secrets** (.env, credentials.json, etc.) before committing.
- **Don't force-push** unless explicitly asked.
- **Use non-destructive git commands by default.** Destructive operations (reset --hard, clean -f) require explicit permission.

## Commit Hygiene

- One logical change per commit when practical
- If a session produces multiple unrelated changes, separate commits are fine
- Commit messages should be descriptive enough to understand the change without reading the diff
