---
inclusion: manual
---

# Product — Cost & Reliability

## Cost Philosophy

This tool should cost roughly **$3-4/day** in API costs during active job searching (~$90-120/month). That's the price of a premium job board subscription, but with full automation. If costs spike significantly above that without a corresponding increase in applications submitted, something is wrong with the filtering or retry logic.

## Claude API Token Budget

Claude is the only paid service. Every token counts, but don't sacrifice application quality to save pennies.

### Token Conservation Strategies

1. **Pre-filter before scoring.** Keyword matching, salary filtering, and deduplication should eliminate 60-80% of jobs before Claude ever sees them.
2. **Cache keyword lists.** Generate the keyword set once per goals change, not per run.
3. **Short prompts, structured output.** Don't send the entire job description if a summary suffices. Request JSON responses to avoid parsing overhead.
4. **Don't re-score.** Once a job has a score, it keeps that score. Never re-evaluate unless goals change.
5. **Batch when possible.** If multiple jobs need scoring in one run, consider whether a single prompt with multiple jobs is cheaper than N individual calls (test this — depends on context window pricing).

### Cost Monitoring

- Log token usage per API call (input tokens, output tokens)
- Track daily/weekly spend in the database
- Alert (via notification) if daily spend exceeds $8 — something is probably looping or retrying excessively
- Surface cost-per-application as a metric so the user can see value

## Reliability Principles

The tool runs unattended. It must handle failures gracefully without human intervention for routine issues.

### Retry Strategy

- **Network errors / timeouts:** Retry 3x with exponential backoff (2s, 8s, 30s)
- **Claude API rate limits:** Back off and retry after the suggested wait time
- **LinkedIn page load failures:** Retry once, then skip that job and continue
- **Browser crash:** Restart the browser session and resume from the last checkpoint
- **Auth expiration (Gmail, Google Docs):** Notify the user. Don't retry — it won't help.

### What "Resume from Checkpoint" Means

The pipeline processes jobs in stages. If it crashes mid-run:
- Jobs already scored keep their scores
- Jobs already applied keep their status
- The next run picks up where it left off based on database state
- No job gets applied to twice (dedup by job ID)

### Anti-Detection & Rate Limiting

LinkedIn will ban accounts that behave like bots. The tool must look human:

- Randomized delays between actions (not fixed intervals)
- Card clicks: 1.5-4s delay
- Page navigation: 5-12s delay
- Between search queries: 10-20s delay
- Never run more than one search cycle per hour
- Respect LinkedIn's implicit rate limits — if pages start loading slowly or showing CAPTCHAs, back off for 30+ minutes
- Use a real Chrome profile with real browsing history (CDP connection to user's Chrome)

### Scheduling

- Run daily during business hours (8 AM - 8 PM in the user's timezone)
- Hourly checks for new jobs
- Don't run on weekends unless explicitly configured (most jobs posted Mon-Fri)
- If a run takes longer than expected, don't overlap with the next scheduled run

### Data Integrity

- SQLite with WAL mode for crash safety
- Never delete job records — only update status
- Backup the database daily (copy to timestamped file in data/backups/)
- If the database is corrupted, the tool should refuse to start and notify rather than silently creating a new empty database

## Performance Targets

- Discovery + scoring for 20 new jobs: < 5 minutes
- Single Easy Apply submission: < 60 seconds
- Single External Apply submission: < 3 minutes
- Full daily cycle (discovery + scoring + applications): < 30 minutes total
- Extension API response time: < 200ms for all endpoints

## Resource Usage

- Docker container memory: < 512MB baseline, < 1GB during Playwright operations
- CPU: minimal except during active browser automation
- Disk: < 1GB for database + PDFs + logs (rotate logs weekly)
- Network: only outbound to LinkedIn, Claude API, Gmail, Google Docs/Apps Script
