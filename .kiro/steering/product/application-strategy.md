---
inclusion: manual
---

# Product — Application Strategy

## Goal

Maximize the number of quality applications submitted per day while minimizing wasted effort (applications to jobs that won't respond, or jobs that are a poor fit).

## Scoring Philosophy

The AI scoring exists to answer one question: "If the user applied to this job, is there a realistic chance they'd get an interview?"

This is NOT about whether the user would enjoy the job, whether it's their dream role, or whether it's a perfect match. It's about whether their background is credible enough for this role that a recruiter would put them in the "yes" pile.

### Scoring Calibration

- **85-100:** Strong fit. Auto-apply. The user's background clearly qualifies them.
- **70-84:** Plausible fit. Auto-apply with tailored resume. Might be a stretch but worth the shot.
- **50-69:** Borderline. Send to human queue. Could go either way — user's judgment needed.
- **Below 50:** Skip. Don't waste the application. The gap is too large.

### What the Scoring Evaluates

The scoring prompt receives the user's goals profile (their background, target roles, preferences) and the job description. It evaluates:
- Does the user's experience match what the role requires?
- Are there deal-breakers (location, clearance, specific certs without "or equivalent")?
- Is the seniority level appropriate?
- Does the salary range (if visible) meet the user's minimum?

The scoring does NOT make subjective quality-of-life judgments. Those belong in the human queue.

## Pre-Filtering Strategy

Before spending Claude tokens on scoring, filter aggressively:

1. **Keyword match:** Job must contain ≥2 of the cached keyword set (generated from the user's goals profile)
2. **Salary floor:** If salary is visible and below minimum, skip immediately
3. **Deduplication:** Same company + same title = skip (already seen)
4. **Already viewed:** Skip LinkedIn "Viewed" cards (configurable)

These filters cost zero tokens and eliminate 60-80% of irrelevant results.

## Resume Tailoring Strategy

Tailoring should be surgical, not a rewrite:

- Swap 3-5 bullet points or phrases to emphasize relevant experience
- Match terminology from the job description (e.g., if the JD says "vulnerability management program" and the resume says "vulnerability management", match their phrasing)
- Never fabricate experience. Only reframe existing experience to highlight relevance.
- Keep the overall structure and formatting identical to the master resume

## Application Completeness

A submitted application must be complete. Partial submissions are worse than no submission:

- All required fields filled
- Resume uploaded (tailored PDF)
- Cover letter included if required (AI-generated, brief, specific to the role)
- No placeholder text, no "N/A" in required fields
- If a field can't be filled confidently, stop and send to human queue rather than guessing

## External Apply Strategy

External applications (Greenhouse, Lever, Workday, etc.) are higher effort but often higher quality:

- Only attempt external apply for jobs scoring above the configurable threshold (default ≥80)
- If the form is too complex or hits an unsolvable obstacle (CAPTCHA, unsupported ATS), mark as "needs_manual" and notify the user with the direct link
- Track which ATS platforms succeed/fail to improve over time

## Volume vs. Quality Tradeoff

The right balance: **apply to every job that's a plausible fit, but never submit a bad application.**

- It's better to apply to 10 jobs with tailored resumes than 50 with a generic one
- It's better to skip a borderline job than to submit with wrong information
- It's better to notify the user about a stuck application than to force it through
