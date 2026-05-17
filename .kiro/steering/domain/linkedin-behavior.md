---
inclusion: manual
---

# Domain — LinkedIn Behavior & Anti-Detection

## How LinkedIn Job Search Works

### Page Structure

- Job search results are a two-panel layout: job cards on the left, detail panel on the right
- Clicking a card loads the full description in the right panel (no page navigation)
- Results are paginated (25 jobs per page), loaded via scroll or "Next" button
- Job cards contain: title, company, location, posted date, Easy Apply badge, "Viewed" indicator
- The detail panel contains: full description, salary (if disclosed), apply button, company info

### Data Sources (in order of reliability)

1. **JSON-LD structured data** (schema.org JobPosting) — Most reliable for company name, title, location, salary. LinkedIn maintains this for Google Jobs indexing. Unlikely to break.
2. **DOM selectors** — Fragile. LinkedIn changes class names and structure regularly. Use as fallback only.
3. **URL parameters** — Search query, location, filters are encoded in the URL. Stable and parseable.

### Easy Apply vs. External Apply

- **Easy Apply:** Application happens entirely within LinkedIn's modal. Multi-step form (1-5 steps). Fields vary by employer configuration. Resume upload, contact info, custom questions.
- **External Apply:** "Apply" button redirects to the employer's ATS. LinkedIn's involvement ends at the redirect. The URL in the button is the external application link.

Detection: Look for the "Easy Apply" badge on the job card or the button text in the detail panel.

### Job Card Staleness

- Cards can appear in search results even after the job is closed
- "Viewed" indicator means the user's account has previously clicked this card
- Posted date can be "30+ days ago" — these are often stale or reposted
- Some cards are "Promoted" (paid placements) — they appear at the top regardless of relevance

## Anti-Detection Strategy

LinkedIn actively detects and restricts bot behavior. The tool connects to the user's real Chrome session via CDP specifically to avoid detection.

### Why CDP to Real Chrome (Not Headless)

- Real Chrome has real cookies, real browsing history, real session state
- LinkedIn fingerprints browser instances — headless Chrome has detectable differences
- The user's account has organic activity patterns that make automated actions blend in
- No need to handle login, 2FA, or session management — the user is already logged in

### Behavioral Patterns That Trigger Detection

| Behavior | Risk Level | Mitigation |
|----------|-----------|------------|
| Fixed-interval actions | High | Randomized delays (gaussian distribution, not uniform) |
| Clicking cards without reading | Medium | Wait 3-8s on detail panel before moving to next |
| Navigating faster than human scroll speed | High | Simulate realistic scroll patterns |
| Hundreds of page views per hour | Critical | Cap at 50-60 job views per hour max |
| Applying to 50+ jobs in one session | High | Cap at 10-15 applications per session |
| Accessing pages without referrer chain | Medium | Always navigate from search results, never direct URL |
| Running 24/7 | Medium | Only run during business hours |

### Delay Configuration

- Card click → detail panel load: 1.5-4s (random)
- Reading detail panel before next action: 3-8s
- Page navigation (next page of results): 5-12s
- Between search queries: 10-20s
- Between application submissions: 30-60s
- If CAPTCHA detected: stop immediately, back off 30+ minutes, notify user

### Session Management

- Connect to Chrome via CDP (Chrome DevTools Protocol)
- Auto-discover the WebSocket URL from Chrome's debug endpoint
- 3-strategy fallback for WebSocket discovery (HTTP endpoint, file-based, port scan)
- If Chrome is not running or debug port is not open: fail loudly, notify user
- Never launch a new Chrome instance — always attach to existing

### What Happens When Detected

- Soft restriction: pages load slowly, search results are limited, CAPTCHAs appear
- Hard restriction: account gets a temporary ban (24-72 hours), "unusual activity" warning
- Nuclear: account permanently restricted (rare, usually requires extreme abuse)

**Response to soft restriction:** Back off for 30+ minutes. Reduce activity for the rest of the day. Log the event.

**Response to hard restriction:** Stop all activity. Notify user immediately. Do not retry.

## LinkedIn-Specific Gotchas

- Job IDs are numeric strings (e.g., "3987654321") extracted from the URL or data attributes
- The same job can appear in multiple search queries — dedup by job ID
- "Promoted" jobs may not match the search criteria at all — pre-filter still applies
- Salary information is inconsistently formatted: "$120K-$150K", "$60/hr", "Competitive", or absent
- Remote/hybrid/on-site is sometimes in the title, sometimes in metadata, sometimes only in the description
- LinkedIn occasionally A/B tests different page layouts — selectors may work for some users but not others
