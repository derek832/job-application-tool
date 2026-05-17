---
inclusion: manual
---

# Product — User Experience

## Core UX Principle

The user is not a developer using a developer tool. They're a job seeker who may have zero technical background. The interface should feel like a polished consumer product, not a debug dashboard.

## Interaction Budget

- **Normal day:** 0–5 minutes. Glance at dashboard, approve/skip 1-2 borderline jobs, done.
- **Active day:** 10–15 minutes. Review a batch of human-queue items, tweak a search query, check application history.
- **Setup/config day:** 30+ minutes. Acceptable only during initial setup or major preference changes.

## Notification Philosophy

Notifications exist to get the user's input when it changes an outcome. They are not status updates.

**Send a notification when:**
- A borderline job needs a human decision (approve/skip)
- An application failed in a way that requires manual intervention
- The system is broken and can't self-recover (auth expired, browser crashed)

**Never notify for:**
- Successful applications (check the dashboard if curious)
- Jobs that were auto-skipped (that's the whole point)
- System health when healthy (no "all clear" messages)
- Daily summaries (the dashboard IS the summary)

## Human Queue Design

The human queue is the highest-value interaction point. Design it for speed:

- Show the job title, company, salary range, and fit score at a glance
- Show the 2-3 sentence AI reasoning for why it's borderline
- Two big buttons: Approve / Skip. That's it.
- Optional: "View full description" expandable, but don't require it for a decision
- Queue items expire after 48 hours → auto-skip. Don't let the queue become a guilt pile.

## Error Messages

When something goes wrong, tell the user:
1. What happened (one sentence, plain English)
2. Whether it's blocking applications or just one job
3. What to do about it (specific action, not "check logs")

Bad: "CDP connection failed: WebSocket handshake error"
Good: "Can't connect to Chrome. Make sure Chrome is open with the debug flag. [How to fix]"

## Settings Design

- Group settings by what they affect, not by technical category
- Use plain language labels: "Minimum salary" not "min_salary_threshold"
- Show the effect of a change: "Currently skipping jobs below $100,000/year"
- Dangerous settings (like lowering the fit threshold) should show a warning about what changes

## Dashboard

The dashboard answers one question: "Is the tool working and finding me jobs?"

- Current status (running / paused / error)
- Last run time and next scheduled run
- Stats: jobs found today, applications submitted today, in queue
- Recent activity feed (last 5-10 actions, one line each)

Keep it scannable. No charts, no graphs, no analytics deep-dives on the main view.
