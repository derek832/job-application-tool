# Git Workflow — Branch, Deploy, Verify, Merge

## Purpose

This steering file ensures all code changes follow a branch → deploy → verify → merge workflow. Main represents "known working code." Nothing merges to main until it has been observed working in a live pipeline run.

## The Workflow

### 1. Create a Branch

Before writing any code:

```
git checkout main
git pull origin main
git checkout -b <branch-type>/<short-description>
```

Branch naming:
| Work Type | Pattern | Example |
|---|---|---|
| Bug fix | `fix/<description>` | `fix/rollback-integrity-error` |
| Feature | `feat/<description>` | `feat/per-job-commits` |
| Refactor | `refactor/<description>` | `refactor/pipeline-flow` |

### 2. Implement and Commit

- Make the change
- Stage specific files (`git add <files>`, not `git add -A` unless all changes are related)
- Commit with a conventional message: `fix:`, `feat:`, `refactor:`, `test:`, `chore:`
- Keep subject under 72 characters

### 3. Push the Branch

```
git push -u origin <branch-name>
```

This ensures the branch exists on GitHub regardless of what happens next.

### 4. Deploy to Local Containers

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

The running containers now have the branch code. This IS the test environment.

### 5. Verify with a Live Run

**This is the critical step.** Do NOT merge until verification passes.

For pipeline-affecting changes (anything in `automator/src/`):
- Wait for the next scheduled pipeline run, OR trigger a manual run
- Observe the run via `docker compose logs automator --tail=100`
- Confirm: no crashes, no `pipeline_fatal_error`, expected behavior in logs
- Check the web app: jobs appearing, correct statuses, no 504s

For frontend-only changes:
- Refresh the web app and confirm the change works visually
- No need to wait for a pipeline run

For test-only or docs-only changes:
- Run the test suite: `python -m pytest tests/ -q`
- Merge immediately after tests pass (no live run needed)

### 6. Merge to Main

Only after verification passes:

```
git checkout main
git pull origin main
git merge <branch-name> --no-edit
git push origin main
```

### 7. Stay on the Branch for Follow-ups

If the verification reveals issues:
- Stay on the branch
- Fix the issue, commit, push
- Rebuild containers
- Re-verify
- Only merge once it's clean

## Rules

- **Never commit directly to main.** Always use a branch.
- **Never merge without verification.** The merge is the "this works" signal.
- **Always push the branch before deploying.** GitHub should have the code even if verification fails.
- **Always rebuild after commit.** Don't leave stale containers running old code.
- **One branch per logical change.** Don't mix unrelated fixes on one branch.
- **Keep merged branches.** They serve as history. Don't delete them.
- **Don't force-push** unless explicitly asked.

## When Multiple Fixes Happen in One Session

If you're iterating on several bugs in one conversation:
- Each fix gets its own branch
- Deploy and verify each one before merging
- If fixes are interdependent (fix B depends on fix A), stack them: merge A first, then branch B from updated main

## Exception: Trivial Non-Code Changes

These can go directly to main without a branch:
- README/docs-only edits
- Steering file updates
- TODO.md updates
- .gitignore changes

Everything that touches `automator/src/`, `webapp/src/`, `docker-compose.yml`, or `Dockerfile` MUST go through the branch workflow.
