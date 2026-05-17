---
inclusion: manual
---

# Engineering — Security Standards & Dependency Hygiene

## Dependency Management

### Pinning
- All Python dependencies must be pinned to exact versions in `requirements.txt` (e.g., `fastapi==0.111.0`, not `fastapi>=0.111`).
- All Node/TypeScript dependencies must be pinned to exact versions in `package.json` (use `"fastapi": "0.111.0"`, not `"^0.111.0"`).
- Use `pip-compile` (from `pip-tools`) to generate a fully-resolved `requirements.txt` from `requirements.in`. Never hand-edit `requirements.txt`.
- Use `npm ci` (not `npm install`) in Docker builds to enforce lockfile integrity.

### CVE Scanning
- Before adding any new dependency, search the [OSV database](https://osv.dev) or run `pip-audit` / `npm audit` to check for known vulnerabilities.
- Run `pip-audit --requirement requirements.txt` and `npm audit --audit-level=moderate` as part of the CI/build process.
- If a dependency has an unpatched CVE with CVSS score >= 7.0, do not use it. Find an alternative or implement the functionality directly if it is small enough.
- If a dependency has a CVE with CVSS score < 7.0, document it in a `SECURITY_NOTES.md` file with the CVE ID, affected version, and rationale for accepting the risk.
- Re-run audits weekly (add a scheduled hook or reminder). Dependencies that were clean at install time can become vulnerable.

### Package Vetting
- Before adding any package, verify: it has >1000 GitHub stars OR is an official SDK (e.g., `anthropic`, `google-auth`), it has been updated within the last 12 months, and the package name matches the GitHub repo name exactly (typosquatting check).
- Prefer official SDKs over community wrappers. Use `anthropic` (official), not third-party Claude clients.
- Minimize the dependency tree. If you only need one function from a large library, implement it directly.

## Secrets Handling

- Secrets (API keys, OAuth tokens) are passed exclusively via environment variables or stored as token files on the mounted volume. Never hardcode them.
- Gmail authentication uses OAuth2 with a refresh token stored in `data/gmail_token.json`. The credentials file (`data/gmail_credentials.json`) and token file must be in `.gitignore`.
- Never log secret values. When logging configuration, redact secrets: `claude_api_key=***`.
- The `GET /config/settings` API endpoint must return `"***"` for all secret fields.
- The `.env` file (used for local Docker Compose development) must be listed in `.gitignore` and `.dockerignore`.
- The SQLite DB file contains the config table with secrets — it must also be in `.gitignore`.
- Use `secrets.token_hex(32)` (Python stdlib) for generating the API bearer token. Never use `random` for security-sensitive values.

## Input Validation & Injection Prevention

- All data entering the system from external sources (LinkedIn HTML, Claude API responses, external job site content, Chrome Extension API requests) must be validated against a Pydantic schema before use.
- Job description text extracted from LinkedIn is stored as plain text only. Strip all HTML tags before storing. Never render extracted HTML in the Extension UI as raw HTML.
- When filling form fields via Playwright, sanitize values before typing: strip leading/trailing whitespace, limit length to 500 characters, and reject values containing `<script`, `javascript:`, or SQL injection patterns.
- SQLite queries must use parameterized statements via SQLAlchemy ORM or `?` placeholders. Never use f-strings or string concatenation to build SQL queries.
- The FastAPI API validates all request bodies via Pydantic models. No endpoint accepts raw dicts.

## Network Security

- The FastAPI server binds exclusively to `127.0.0.1`. Never `0.0.0.0`.
- All outbound connections to external APIs (Claude, Gmail, Google) use HTTPS/TLS. Never disable certificate verification (`verify=False` is forbidden).
- Playwright browser instances have no exposed ports. They communicate via CDP inside the Docker network only.
- Docker Compose must not publish any ports to external network interfaces. Allowed localhost bindings: `127.0.0.1:3000:3000` (frontend/nginx) and the automator port exposed internally only within the Docker network. The LAN server (Wave 1) may additionally bind to a user-configured LAN IP for mobile queue access.

## Docker Security

- Use official base images with pinned digest hashes (e.g., `python:3.11.9-slim@sha256:...`), not floating tags like `python:3.11-slim`.
- Run the Automator process as a non-root user inside the container. Add `USER appuser` to the Dockerfile.
- Set `read_only: true` on the container filesystem where possible; mount only the specific volume paths that need write access.
- Do not install `curl`, `wget`, or other network tools in the production image unless required.
- Use multi-stage Docker builds to keep the final image minimal.

## Web App Security (Post Wave 0)

After Wave 0, the Chrome Extension is removed and replaced by a React SPA served by nginx at `http://127.0.0.1:3000`.

- The Bearer token is stored in `localStorage` under key `jat_api_token`. This is origin-scoped to `http://127.0.0.1:3000` only.
- The token is never logged, never included in error messages, and never sent to any URL other than `/api/*` (proxied by nginx to the local automator).
- The nginx container runs as a non-root user. The final image contains only nginx and static HTML/JS/CSS — no Node.js, npm, or source code.
- The nginx base image uses a pinned version tag (e.g., `nginx:1.27.3-alpine`).
- The web app requires zero browser permissions and works in any modern browser without extensions.

## Chrome Extension Security (DEPRECATED — Removed after Wave 0)

> **Note:** This section applies only to the pre-Wave-0 architecture where a Chrome Extension served as the UI. After Wave 0 completes and the `extension/` directory is removed, these rules no longer apply. See "Web App Security" above for the replacement guidance.

- The extension's `manifest.json` must declare the minimum required permissions. Do not request `<all_urls>` — scope host permissions to `http://127.0.0.1:7432/*` and `https://www.linkedin.com/*` only.
- The extension must not use `eval()` or `new Function()` anywhere. This is enforced by Manifest V3's CSP.
- The API bearer token stored in Chrome extension storage uses `chrome.storage.local` (not `sessionStorage` or `localStorage`), and is never included in any log or error message displayed to the user.
- Content Security Policy in `manifest.json` must explicitly disallow inline scripts.
