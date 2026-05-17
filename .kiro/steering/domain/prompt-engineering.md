---
inclusion: manual
---

# Domain — Prompt Engineering

## Why This Matters

The Claude prompts are the core intelligence of this product. A 5% improvement in scoring accuracy means fewer wasted applications and more interviews. A poorly calibrated prompt wastes money on bad scores or misses good opportunities. Treat prompts with the same rigor as production code.

## Prompt Design Principles

### 1. Structured Input, Structured Output

Every prompt follows the same pattern:
- System prompt: defines Claude's role and constraints
- User prompt: provides structured data sections (## headers) + clear instructions
- Output format: explicitly specified JSON schema or text format

This structure makes responses predictable and parseable. Never rely on Claude to "figure out" what format you want.

### 2. Constraints Over Instructions

Tell Claude what NOT to do more than what to do:
- "Never fabricate experience" > "Be truthful"
- "Do NOT change company names or dates" > "Keep factual information accurate"
- "Respond with ONLY valid JSON, no commentary" > "Please format as JSON"

Negative constraints are more reliably followed than positive instructions.

### 3. One Task Per Prompt

Each API call does exactly one thing:
- `score_fit` → scores a job and returns structured result
- `tailor_resume` → generates find/replace pairs
- `generate_cover_letter` → writes a cover letter
- `identify_form_fields` → identifies form fields from a screenshot

Don't combine tasks. A prompt that scores AND tailors will do both worse than two separate prompts.

### 4. Provide All Context Upfront

Claude can't ask follow-up questions. Every prompt must include everything needed to produce the answer:
- The full job description (not a summary)
- The full resume content (not highlights)
- The goals profile (preferences, deal-breakers, target titles)
- Any supplementary context that affects the decision

Missing context → worse output → wasted tokens on retries or bad decisions.

## Prompt-Specific Guidance

### Fit Scoring Prompt

**Goal:** Produce a calibrated 0-100 score that predicts interview likelihood.

**Key design decisions:**
- Score represents "would a recruiter put this in the yes pile?" — not "would the user enjoy this job?"
- Deal-breaker detection is contextual — Claude evaluates whether the term applies to the role level, not just whether the word appears
- Rationale is capped at 200 words — forces concise reasoning, reduces output tokens
- JSON-only response — no prose, no explanation outside the schema

**Calibration risks:**
- Score inflation: Claude tends to be generous. The thresholds (good_fit=75, stretch=60 by default) account for this.
- Deal-breaker false positives: Words like "Associate" appear in many contexts. The prompt explicitly instructs Claude to evaluate context, not just presence.
- Inconsistency between runs: The same job should get roughly the same score (±5 points) on repeated scoring. If it doesn't, the prompt needs more specificity.

**When to modify this prompt:**
- If too many obviously bad jobs are scoring above threshold → tighten the scoring criteria
- If good jobs are being skipped → loosen criteria or lower thresholds (prefer threshold change over prompt change)
- If deal-breakers are triggering incorrectly → add more context examples to the deal-breaker instruction

### Resume Tailoring Prompt

**Goal:** Produce find/replace pairs that optimize ATS keyword matching without fabricating experience.

**Key design decisions:**
- Find strings must be EXACT substrings — this is enforced by the Google Docs find/replace API
- Short find strings (one phrase/clause) — avoids matching issues with formatting boundaries
- 8-15 replacements target — enough to make a difference, not so many that the resume becomes unrecognizable
- Never change headers, names, dates, or company names — these are verifiable facts
- Supplementary context is provided for richer keyword matching but explicitly excluded from output

**Common failure modes:**
- Find string doesn't exist in the resume (Claude hallucinated or paraphrased) → the replacement silently fails
- Find string spans a bold/non-bold boundary → formatting gets corrupted in the PDF
- Too many replacements make the resume sound generic → cap at 15 and prioritize quality
- Claude adds skills the user doesn't have → the "never fabricate" constraint must be prominent

### Cover Letter Prompt

**Goal:** Generate a brief, specific cover letter that references the actual job and company.

**Key design decisions:**
- 250-400 words — short enough to be read, long enough to be substantive
- Must reference the specific job title and company name — no generic letters
- Highlights 2-3 relevant qualifications from the tailored resume
- No fabrication — only references experience that exists in the resume

### Vision Form Identification Prompt

**Goal:** Identify all form fields in a screenshot and suggest values from the user profile.

**Key design decisions:**
- Uses Claude's vision capability (image input)
- Returns structured JSON array of field objects
- Each field has: id, label, type, suggested_value
- Suggested values come from the user profile — Claude maps profile data to form fields
- Unknown fields get `null` suggested_value (don't guess)

**Unique challenges:**
- Screenshot quality affects accuracy — ensure full-page, high-resolution captures
- Overlapping elements or modals can confuse field identification
- Some fields are hidden behind dropdowns or conditional logic — only visible fields can be identified
- CAPTCHA detection is critical — if Claude identifies a CAPTCHA field, the whole form should be flagged

## Response Parsing

### JSON Extraction

Claude sometimes wraps JSON in markdown code blocks (```json ... ```). The `_extract_json` helper handles this:
1. Strip leading/trailing whitespace
2. Remove markdown code block wrapper if present
3. If response doesn't start with `{` or `[`, scan for the first occurrence
4. Return cleaned string for `json.loads()`

### Validation

Every parsed response goes through Pydantic validation:
- `FitScoreResult` for scoring (validates score range, required fields)
- `list[FormField]` for vision (validates field structure)
- Raw string for tailoring and cover letters (validated downstream)

If validation fails → raise the appropriate domain exception → the retry logic handles it.

## Prompt Versioning

Prompts are currently inline in `claude_client.py`. When modifying prompts:

1. **Don't change prompts casually.** A scoring prompt change affects every future job evaluation.
2. **Test against known inputs.** Before deploying a prompt change, run it against 5-10 jobs with known expected scores. Verify the results are reasonable.
3. **Log the change.** Note what changed and why in the commit message. If scores shift significantly, it should be traceable.
4. **One change at a time.** Don't modify the scoring prompt and the tailoring prompt in the same commit. If results change, you need to know which prompt caused it.

## Token Efficiency

### Input Token Reduction

- Job descriptions can be 2,000-5,000 tokens. Don't truncate — Claude needs the full context for accurate scoring.
- Resume content is typically 800-1,500 tokens. Always send the full resume.
- Goals profile is compact JSON (~200-400 tokens). Always include.
- System prompts are short (~50-100 tokens). Don't over-engineer them.

### Output Token Reduction

- JSON-only responses eliminate prose overhead
- Capped rationale (200 words) prevents verbose explanations
- Structured output format means no "Here's my analysis:" preamble
- `max_tokens=4096` is generous — actual responses are usually 200-800 tokens

### When Tokens Are Worth Spending

- Full job description for scoring: always worth it (accuracy > cost)
- Supplementary context for tailoring: worth it (better keyword matching)
- Cover letter generation: only when required by the application
- Vision calls: expensive (image tokens) but necessary for external apply

### When to Save Tokens

- Don't re-score jobs that already have scores
- Don't generate cover letters for Easy Apply (rarely required)
- Don't run vision on forms that can be filled with DOM inspection alone
- Cache keyword lists — don't regenerate unless goals change
