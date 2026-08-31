---
inclusion: always
---

# Product Development — Master Router

## Purpose

This is the top-level product development steering file. It evaluates the current task and pulls in the appropriate sub-context. The goal of this product is singular: **get the user a job**. Every decision flows from that.

## Product Mission

This tool exists to maximize the number of quality job applications submitted with minimal user effort. "Quality" means: the job is a genuine fit, the resume is tailored, and the application is complete. "Minimal effort" means: the user should spend less than 5 minutes per day interacting with this tool on a normal day.

## Decision Framework — Which Sub-File Applies

### If the task involves user-facing behavior, UI, notifications, or workflow:
→ Load #[[file:.kiro/steering/product/user-experience.md]]

Applies to: Chrome Extension UI, notification content/timing, human queue flow, settings design, onboarding, error messages shown to the user, dashboard layout.

### If the task involves the job matching pipeline, scoring, filtering, or application strategy:
→ Load #[[file:.kiro/steering/product/application-strategy.md]]

Applies to: Claude scoring prompts, fit thresholds, deal-breaker logic, keyword pre-filtering, search query design, apply/skip decisions, resume tailoring strategy, external apply behavior.

### If the task involves cost, performance, reliability, or operational efficiency:
→ Load #[[file:.kiro/steering/product/cost-and-reliability.md]]

Applies to: Claude API token usage, retry logic, rate limiting, scheduling, error recovery, Docker resource usage, browser session stability, anti-detection measures.

### If the task spans multiple areas or is a new feature end-to-end:
→ Load all three sub-files.

## Universal Product Principles (Always Apply)

1. **Ship what works.** A feature that applies to 80% of jobs today beats a perfect feature next month. The user is job hunting now.
2. **Never waste an application.** A botched submission is worse than no submission. If something looks wrong, stop and notify rather than submitting garbage.
3. **Respect the user's time.** Only interrupt when the user's input genuinely changes the outcome. Notifications should be actionable, not informational.
4. **Privacy is non-negotiable.** Everything runs locally. No telemetry, no analytics, no cloud services beyond what's explicitly configured.
5. **Cost-aware by default.** Every Claude API call costs money. Don't score jobs that obviously don't fit. Don't tailor resumes for jobs that won't get applied to. Pre-filter aggressively.
