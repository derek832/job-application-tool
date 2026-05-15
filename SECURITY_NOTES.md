# Security Notes

This file documents accepted CVE risks and security decisions for the job-application-tool project.
Per the security standards, any dependency with a CVE scoring < 7.0 CVSS that is accepted must be
logged here with rationale. Dependencies with CVSS >= 7.0 must not be used.

## CVE Acceptance Log

| Date | Package | Version | CVE ID | CVSS | Rationale |
|------|---------|---------|--------|------|-----------|
| — | — | — | — | — | No accepted CVEs at this time |

## Audit Schedule

CVE audits are run:
- Before adding any new dependency
- Weekly via `pip-audit --requirement automator/requirements.txt`
- Weekly via `npm audit --audit-level=moderate` in `extension/`

## Security Decisions

### API Token Generation
The Automator generates its bearer token using `secrets.token_hex(32)` (Python stdlib).
This produces a 256-bit cryptographically random token. Never use `random` for this purpose.

### LinkedIn Session Handling
The Automator uses a Playwright persistent browser context with a user-data directory
mounted on the Docker volume. No LinkedIn credentials are stored — only session cookies
persisted by the browser. The user logs in manually once.

### SQLite DB Access
The `state.db` file is stored on the host-mounted volume. It contains the config table
which holds API keys and credentials. The user is responsible for filesystem-level access
control on the host. The DB file is listed in `.gitignore` and `.dockerignore`.
