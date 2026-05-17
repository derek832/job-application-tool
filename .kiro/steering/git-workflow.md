# Git Workflow — Automatic Branch Management

## Purpose

This steering file ensures all implementation work happens on feature branches, never directly on `main`. It applies to spec task execution, bug fixes, and any code changes.

## Before Starting Work

Before writing any code or making any file changes for a feature, task, or fix:

1. **Check the current branch** — run `git branch --show-current`
2. **If on `main`**, create and switch to a new branch:
   - For spec features/waves: `feat/<feature-name>` (e.g., `feat/wave-1-notifications-mobile`)
   - For individual tasks: `feat/<task-id>-<short-description>` (e.g., `feat/2.1-ntfy-client`)
   - For bug fixes: `fix/<short-description>` (e.g., `fix/rate-limiter-off-by-one`)
3. **If already on a feature branch** that matches the current work, continue on it.
4. **Always pull latest main first** before branching:
   ```
   git checkout main
   git pull origin main
   git checkout -b feat/<branch-name>
   ```

## After Completing Work

When a feature, spec wave, or fix is fully implemented and tests pass:

1. **Stage all relevant files** — prefer `git add <specific files>` over `git add -A` to avoid committing unrelated changes. Use `git add -A` only when all changes are related to the current feature.
2. **Commit with a conventional commit message**:
   - `feat: <description>` — new feature or capability
   - `fix: <description>` — bug fix
   - `refactor: <description>` — code restructuring
   - `test: <description>` — test additions/changes only
   - `chore: <description>` — build, config, dependencies
3. **Push the branch** with tracking: `git push -u origin <branch-name>`
4. **Rebuild containers** (see "After Push: Rebuild Containers" below).
5. **If rebuild succeeds, merge into main**:
   ```
   git checkout main
   git pull origin main
   git merge <branch-name> --no-edit
   git push origin main
   git checkout <branch-name>
   ```
6. **If rebuild fails**, fix the issue on the feature branch before merging.

This prevents branch rot — branches are merged immediately after a successful build, not left dangling for manual PR review.

## Branch Naming Convention

| Work Type | Branch Pattern | Example |
|---|---|---|
| Spec wave/feature | `feat/<feature-name>` | `feat/wave-1-notifications-mobile` |
| Individual spec task | `feat/<task-id>-<description>` | `feat/2.1-ntfy-client` |
| Bug fix | `fix/<description>` | `fix/scoring-threshold-boundary` |
| Refactor | `refactor/<description>` | `refactor/notification-service` |

## After Push: Rebuild Containers

After committing and pushing, rebuild the Docker containers that were affected by the changes:

1. **Determine which containers were touched** based on the files changed:
   - Changes in `automator/` → rebuild `automator`: `docker compose build automator`
   - Changes in `webapp/` → rebuild `frontend`: `docker compose build frontend`
   - Changes in `docker-compose.yml` or root config → rebuild all: `docker compose build`
2. **Restart the affected services**: `docker compose up -d`
3. **Check logs** to verify clean startup: `docker compose logs <service> --tail=30`

This ensures the running containers always reflect the latest committed code.

## Rules

- **Never commit directly to `main`**. Always use a feature branch.
- **One branch per logical unit of work** — a spec wave, a feature, or a fix. Don't mix unrelated changes.
- **Check branch before first file edit** — this is the most important rule. If you're about to write code and you're on `main`, stop and branch first.
- **Merge after successful rebuild** — don't leave branches unmerged. Merge into main immediately after containers build and start cleanly.
- **Keep merged branches** — don't delete branches after merging. They serve as a history of what was done. Use `git branch --merged main` to see them.
- **Commit messages under 72 characters** for the subject line. Use the body for details if needed.
- **Don't force-push** unless explicitly asked.
- **Always rebuild after commit** — don't leave stale containers running with old code.
