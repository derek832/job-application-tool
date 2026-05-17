---
inclusion: always
---

# Engineering — Master Router

## Purpose

This is the top-level engineering steering file. It evaluates the current task and pulls in the appropriate sub-context for coding standards, workflow, and security.

## Decision Framework — Which Sub-File Applies

### If the task involves writing or modifying code (Python or TypeScript):
→ Load #[[file:.kiro/steering/engineering/coding-standards.md]]

Applies to: new features, bug fixes, refactors, code review, function signatures, error handling patterns, logging, type annotations, file organization.

### If the task involves build/test/deploy workflow, git, Docker, or environment setup:
→ Load #[[file:.kiro/steering/engineering/dev-workflow.md]]

Applies to: running tests, adding dependencies, Docker builds, git branching, PR creation, pre-commit checks, project structure, environment variables, Google Apps Script deployment.

### If the task involves security, secrets, dependencies, input validation, or network config:
→ Load #[[file:.kiro/steering/engineering/security-standards.md]]

Applies to: adding packages, CVE scanning, secret handling, API token generation, input sanitization, Docker hardening, Chrome extension permissions, network binding.

### If the task involves the job lifecycle, status transitions, or pipeline stage behavior:
→ Load #[[file:.kiro/steering/engineering/state-machine.md]]

Applies to: adding/modifying statuses, pipeline stage logic, retry behavior, human queue routing, transition audit logging, terminal state handling.

### If the task involves writing or running tests:
→ Load #[[file:.kiro/steering/engineering/testing-strategy.md]]

Applies to: new test files, test fixtures, mocking strategy, property-based tests, coverage decisions, what to test vs. what to skip.

### If the task involves writing code that also touches security (common case):
→ Load both coding-standards and security-standards.

### If the task is a full feature implementation:
→ Load all sub-files relevant to the feature.

## Universal Engineering Principles (Always Apply)

1. **Production quality.** This is not a prototype. Every commit should be deployable.
2. **Type safety everywhere.** Python type annotations on all functions. TypeScript strict mode. Pydantic for data boundaries. Zod for API responses.
3. **Async by default.** The automator is async. Never block the event loop.
4. **Test what matters.** Core pipeline logic gets 80%+ coverage. Mock external services at the boundary.
5. **Zero warnings.** Ruff, Black, ESLint, and TypeScript must all pass clean before any commit.
