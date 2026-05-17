---
inclusion: always
---

# Domain Knowledge — Master Router

## Purpose

This is the top-level domain knowledge steering file. It provides context about how the external world works — LinkedIn's behavior, ATS systems, recruiting practices, and prompt engineering for Claude. This knowledge prevents technically correct but strategically wrong decisions.

## Decision Framework — Which Sub-File Applies

### If the task involves LinkedIn interaction, scraping, navigation, or anti-detection:
→ Load #[[file:.kiro/steering/domain/linkedin-behavior.md]]

Applies to: job discovery, page navigation, Easy Apply modals, search URL construction, DOM selectors, rate limiting, session management, CDP connection.

### If the task involves ATS forms, resume formatting, recruiter behavior, or application strategy:
→ Load #[[file:.kiro/steering/domain/ats-and-recruiting.md]]

Applies to: external apply form filling, resume PDF formatting, keyword optimization, cover letter content, form field mapping, ATS platform quirks (Greenhouse, Lever, Workday).

### If the task involves Claude prompts, scoring calibration, or AI response handling:
→ Load #[[file:.kiro/steering/domain/prompt-engineering.md]]

Applies to: scoring prompts, tailoring prompts, cover letter generation, vision form identification, response parsing, output format stability, prompt versioning.

### If the task spans multiple areas:
→ Load all relevant sub-files.

## Universal Domain Principles (Always Apply)

1. **LinkedIn changes constantly.** DOM selectors, modal flows, and page structure can change without notice. Design for resilience — use multiple selector strategies, fall back gracefully, and log enough to diagnose when something breaks.
2. **ATS systems are inconsistent.** Every platform has quirks. What works on Greenhouse won't work on Workday. Design the external apply system to be platform-aware and fail gracefully on unsupported platforms.
3. **Prompts are the product.** The quality of Claude's scoring and tailoring directly determines whether the user gets interviews. Treat prompts as carefully as production code — version them, test them against known inputs, and don't change them casually.
4. **Recruiters are human.** They spend 6-10 seconds on a resume. The tailoring strategy should optimize for that first scan — keywords in the right places, clear formatting, relevant experience front and center.
