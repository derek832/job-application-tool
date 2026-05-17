---
inclusion: manual
---

# Domain — ATS Systems & Recruiting Practices

## How ATS (Applicant Tracking Systems) Work

### What an ATS Does

An ATS is the software companies use to manage job applications. When someone applies, the ATS:
1. Receives the application (resume, cover letter, form data)
2. Parses the resume into structured fields (name, email, experience, skills)
3. Scores/ranks the application against the job requirements (keyword matching)
4. Presents ranked candidates to the recruiter

### ATS Resume Parsing

ATS parsers are notoriously bad at reading resumes. They work best with:
- Simple formatting (no tables, no columns, no text boxes, no headers/footers)
- Standard section headings (Experience, Education, Skills)
- Plain text content (they ignore formatting — bold, italic, color mean nothing)
- PDF or DOCX format (PDF is safer — DOCX can have parsing issues with complex formatting)

**Critical insight:** ATS parsers read the TEXT, not the visual layout. A beautifully designed resume that looks great to humans may parse as garbage to an ATS. The tailoring strategy should optimize the text content, not the visual presentation.

### Keyword Matching

Most ATS systems do simple keyword matching:
- Exact match on skill terms ("Python", "AWS", "SOC2")
- Phrase matching on job titles ("Security Manager", "Cloud Engineer")
- Some do semantic matching (rare, usually enterprise-tier ATS only)

**Implication for tailoring:** Use the exact terminology from the job description. If the JD says "vulnerability management program" and the resume says "vuln management", change it to match. ATS keyword matching is literal.

## Major ATS Platforms

### Greenhouse
- Clean, modern forms
- Usually 1-3 pages
- Standard fields: name, email, phone, resume upload, cover letter (optional), custom questions
- File upload accepts PDF, DOCX
- Custom questions are usually text fields or dropdowns
- Relatively automation-friendly

### Lever
- Similar to Greenhouse in structure
- Often has a "How did you hear about us?" dropdown
- Resume upload + optional cover letter
- Custom questions vary by employer
- Generally straightforward

### Workday
- Enterprise-grade, complex
- Often requires account creation before applying
- Multi-page forms with many required fields
- May require: work history (manually entered), education details, EEO data
- Frequently has CAPTCHA
- The hardest platform to automate — many employers use it

### iCIMS
- Older platform, less consistent UI
- Sometimes requires account creation
- Form structure varies significantly between employers
- May have unusual field types or validation

### BambooHR
- Simpler, often used by smaller companies
- Usually 1-page forms
- Standard fields, fewer custom questions
- Generally automation-friendly

### Taleo (Oracle)
- Legacy enterprise system
- Complex multi-step forms
- Often requires account creation
- Slow, heavy pages
- Declining in usage but still common at large companies

## Recruiter Behavior

### The 6-Second Scan

Recruiters spend an average of 6-10 seconds on initial resume review. In that time they look for:
1. Current/most recent job title — does it match what they're hiring for?
2. Company names — recognizable companies add credibility
3. Keywords — do they see the skills they're looking for?
4. Years of experience — does it match the level?
5. Location — is the candidate local or willing to relocate?

**Implication:** The most important content goes at the top. The summary/objective and first 2-3 bullet points of the most recent role are what get read. Tailoring should prioritize these sections.

### What Gets an Application Rejected

- No relevant keywords in the first third of the resume
- Job title mismatch (applying for "Senior Engineer" with a "Manager" title — or vice versa)
- Obvious gaps with no explanation
- Generic objective statement that doesn't mention the role
- Resume longer than 2 pages (for most roles)
- Typos in the first paragraph (signals carelessness)

### What Gets an Application Advanced

- Keywords from the JD appearing naturally in experience bullets
- Quantified achievements ("reduced incidents by 40%", "managed $96M in assets")
- Relevant certifications or clearances mentioned early
- Company names that signal relevant industry experience
- A cover letter that references something specific about the company (not generic)

## Form Filling Strategy

### Field Mapping Priority

When the vision agent identifies form fields, map them in this order:
1. **Contact info** (name, email, phone) — from user profile, always available
2. **Resume upload** — always the tailored PDF
3. **Cover letter** — generated if required, skip if optional (unless configured otherwise)
4. **Salary expectation** — use the user's minimum salary from goals profile
5. **Work authorization** — from user profile (yes/no, visa status)
6. **Custom questions** — attempt to answer from profile/goals context, send to human queue if unclear

### Fields to Never Guess

- Social Security Number or government ID
- References (names, phone numbers)
- Specific dates of employment (if not in resume)
- Disability status, veteran status, race/ethnicity (EEO fields — leave blank or select "prefer not to answer")
- Anything requiring a signature or legal acknowledgment

### When to Stop and Notify

- CAPTCHA detected → stop, notify user with direct link
- Required field with no confident answer → stop, notify
- Form has more than 5 pages → likely requires manual attention, notify
- Account creation required and no existing account → notify
- Form asks for information not in the user's profile → notify

## Resume Tailoring Best Practices

### What to Change

- Skill terms → match JD terminology exactly
- Action verbs → use verbs from the JD where natural
- Technical keywords → add relevant ones that are truthfully part of experience
- Summary/objective → align with the specific role
- Bullet point emphasis → reorder or rephrase to highlight relevant experience

### What to Never Change

- Dates of employment
- Company names
- Job titles (these are verifiable)
- Degree names or institutions
- Certifications (don't add ones not held)
- Quantified metrics (don't inflate numbers)

### Format Preservation

The tailoring uses find/replace on the Google Doc. This means:
- Replacements must be exact substrings of the original text
- Bold/italic boundaries must be respected (don't replace across formatting changes)
- Section headers stay untouched
- The overall document structure remains identical
- Only the text content within bullets/paragraphs changes
