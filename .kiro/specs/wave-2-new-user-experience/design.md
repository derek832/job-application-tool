# Design Document: Wave 2 — New User Experience

## Overview

This feature replaces the manual SETUP_GUIDE.md workflow with an in-app guided setup wizard, first-run gating, and integrated troubleshooting. A non-technical user should be able to go from `docker compose up` to a fully operational job search tool without reading documentation, opening a terminal (beyond the initial Docker start), or understanding any infrastructure concepts.

The implementation spans two layers: new backend endpoints on the FastAPI Automator (`GET /setup/status`, `POST /setup/validate/{step}`) and new frontend components in the React web app (Setup Wizard, Diagnostics page, Dashboard health banners). The wizard gates the entire application — no access to Dashboard, Queue, History, or any other page until all 6 configuration steps are validated.

### Key Design Decisions

- **Unauthenticated setup status endpoint** — `GET /setup/status` requires no Bearer token because the user hasn't configured anything yet on first run. The wizard needs to know what's missing before any auth exists.
- **Per-step validation endpoints** — Each wizard step validates independently via `POST /setup/validate/{step}`. This keeps validation logic server-side (where the actual connectivity checks happen) and gives the frontend a uniform interface.
- **Existing config endpoints for persistence** — The wizard collects data and persists it through the same `PUT /config/*` endpoints used by the Settings page. No new persistence layer needed.
- **10-second validation timeout** — All connectivity checks (Claude API, GAS, Gmail) enforce a 10-second ceiling. Non-technical users shouldn't stare at a spinner wondering if something is broken.
- **Plain-English error messages** — Every failure message is written for someone who doesn't know what an HTTP status code is. Messages include the specific action to take, not just what went wrong.
- **Wizard state derived from backend** — The wizard doesn't track its own completion state in localStorage. It queries `GET /setup/status` on load and derives which steps are done. This means partial setups survive browser refreshes and Docker restarts.

---

## Architecture

```mermaid
graph TD
    subgraph "Browser"
        APP[React Web App\nhttp://127.0.0.1:3000]
        WIZARD[Setup Wizard\n6-step flow]
        DIAG[Diagnostics Page]
        DASH[Dashboard\nhealth banners]
    end

    subgraph "nginx :3000"
        PROXY[Reverse Proxy\n/api/* → automator]
    end

    subgraph "FastAPI Automator :7432"
        SETUP_STATUS[GET /setup/status\nunauthenticated]
        SETUP_VALIDATE[POST /setup/validate/{step}\nunauthenticated]
        HEALTH[GET /health\nauthenticated]
        CONFIG[PUT /config/*\nauthenticated]
    end

    subgraph "External Services"
        CLAUDE[Claude API\nAnthropic]
        GAS[Google Apps Script]
        GMAIL[Gmail OAuth]
    end

    APP --> PROXY
    PROXY --> SETUP_STATUS
    PROXY --> SETUP_VALIDATE
    PROXY --> HEALTH
    PROXY --> CONFIG

    SETUP_VALIDATE --> CLAUDE
    SETUP_VALIDATE --> GAS
    SETUP_VALIDATE --> GMAIL

    WIZARD --> SETUP_STATUS
    WIZARD --> SETUP_VALIDATE
    WIZARD --> CONFIG
    DIAG --> HEALTH
    DASH --> HEALTH
```

### Request Flow — First Run

1. User opens `http://127.0.0.1:3000` in browser.
2. React app boots, calls `GET /api/setup/status` (no auth required).
3. Backend checks each config key — returns `{ complete: false, steps: { claude_api: false, ... } }`.
4. App renders the Setup Wizard (all other routes blocked).
5. User fills in Step 1 (Claude API Key), clicks "Next".
6. Frontend calls `POST /api/setup/validate/claude_api` with the key in the request body.
7. Backend makes a test call to Anthropic, returns `{ valid: true, message: "" }`.
8. Frontend advances to Step 2. Repeat for all 6 steps.
9. After Step 6 validates, frontend calls `PUT /api/config/settings`, `PUT /api/config/goals`, `PUT /api/config/profile`, `PUT /api/config/search` to persist all collected data.
10. Frontend shows "Setup Complete" screen, then redirects to Dashboard.

### Request Flow — Returning User with Broken Service

1. User opens the app. `GET /api/setup/status` returns `{ complete: true, ... }`.
2. App renders the normal UI. Dashboard calls `GET /api/health`.
3. Health check returns `{ claude_api: true, gmail: false, google_docs: true }`.
4. Dashboard renders an inline alert banner: "Gmail notifications are down. Your OAuth token may have expired — run 'python authorize_gmail.py' in the automator folder to refresh it."
5. User can also navigate to the Diagnostics page for a full re-check.

---

## Components and Interfaces

### 1. Backend: Setup Status Endpoint

**Route:** `GET /setup/status`  
**Authentication:** None (unauthenticated)  
**Purpose:** Reports which wizard steps have valid configuration.

The endpoint checks each config key in the database and applies the same validation logic used by the per-step validators (but without making external API calls — it only checks data presence/completeness).

```python
# automator/src/api/setup_routes.py

@router.get("/setup/status", response_model=SetupStatusResponse)
async def get_setup_status(
    session: AsyncSession = Depends(get_session),
) -> SetupStatusResponse:
    """Check which wizard steps have valid configuration present."""
    settings = await get_config(session, "settings") or {}
    goals = await get_config(session, "goals_profile") or {}
    profile = await get_config(session, "user_profile") or {}
    search = await get_config(session, "search_config") or {}

    steps = SetupSteps(
        claude_api=bool(settings.get("claude_api_key")),
        google_apps_script=bool(settings.get("gdocs_script_url")),
        gmail=_check_gmail_token_exists(),
        profile=_profile_fields_complete(profile),
        goals=_goals_minimum_met(goals),
        search=_search_has_queries(search),
    )

    return SetupStatusResponse(
        complete=all([
            steps.claude_api,
            steps.google_apps_script,
            steps.gmail,
            steps.profile,
            steps.goals,
            steps.search,
        ]),
        steps=steps,
    )
```

### 2. Backend: Step Validation Endpoints

**Route:** `POST /setup/validate/{step}`  
**Authentication:** None (unauthenticated — user hasn't set up auth yet)  
**Purpose:** Performs live validation for a specific wizard step.

Each step has its own validation logic:

| Step Name | Validation Action | Timeout |
|---|---|---|
| `claude_api` | HTTP GET to `https://api.anthropic.com/v1/models` with provided key | 10s |
| `google_apps_script` | HTTP GET to provided URL | 10s |
| `gmail` | Check OAuth token file exists and is valid | 10s |
| `profile` | Check required fields non-empty after trim | instant |
| `goals` | Check target_titles non-empty and career_objective non-empty | instant |
| `search` | Check at least one keyword or search query present | instant |

```python
@router.post("/setup/validate/{step}", response_model=ValidationResponse)
async def validate_step(
    step: str,
    body: StepValidationRequest,
    session: AsyncSession = Depends(get_session),
) -> ValidationResponse:
    """Validate a single wizard step with live connectivity checks."""
    validators = {
        "claude_api": _validate_claude_api,
        "google_apps_script": _validate_gas_url,
        "gmail": _validate_gmail,
        "profile": _validate_profile,
        "goals": _validate_goals,
        "search": _validate_search,
    }

    if step not in validators:
        raise HTTPException(status_code=404, detail=f"Unknown step: {step}")

    try:
        result = await asyncio.wait_for(
            validators[step](body, session),
            timeout=10.0,
        )
        return result
    except asyncio.TimeoutError:
        return ValidationResponse(
            valid=False,
            message="This check is taking too long. Check your internet connection and try again.",
        )
```

### 3. Backend: Validation Logic Per Step

```python
async def _validate_claude_api(
    body: StepValidationRequest, session: AsyncSession
) -> ValidationResponse:
    """Validate Claude API key by making a test call to the models endpoint."""
    api_key = body.data.get("claude_api_key", "").strip()
    if not api_key:
        return ValidationResponse(valid=False, message="Enter your Claude API key.")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            if response.status_code == 401:
                return ValidationResponse(
                    valid=False,
                    message="This API key was rejected by Anthropic. Double-check that you copied the full key starting with sk-ant-.",
                )
            if response.status_code >= 500:
                return ValidationResponse(
                    valid=False,
                    message="Could not reach the Claude API. Check your internet connection and try again.",
                )
            return ValidationResponse(valid=True, message="")
    except (httpx.RequestError, httpx.TimeoutException):
        return ValidationResponse(
            valid=False,
            message="Could not reach the Claude API. Check your internet connection and try again.",
        )


async def _validate_gas_url(
    body: StepValidationRequest, session: AsyncSession
) -> ValidationResponse:
    """Validate Google Apps Script URL by sending a GET request."""
    url = body.data.get("gdocs_script_url", "").strip()
    if not url:
        return ValidationResponse(valid=False, message="Enter your Apps Script URL.")

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code == 200:
                return ValidationResponse(valid=True, message="")
            if response.status_code == 401:
                return ValidationResponse(
                    valid=False,
                    message="The Apps Script isn't authorized yet. Open the URL in your browser, click 'Review Permissions', and grant access.",
                )
            # Check for authorization error in JSON body
            try:
                json_body = response.json()
                if "authorization" in str(json_body.get("error", "")).lower():
                    return ValidationResponse(
                        valid=False,
                        message="The Apps Script isn't authorized yet. Open the URL in your browser, click 'Review Permissions', and grant access.",
                    )
            except Exception:
                pass
            return ValidationResponse(
                valid=False,
                message=f"Your Apps Script returned an unexpected response (HTTP {response.status_code}). Make sure you copied the full URL ending in /exec.",
            )
    except (httpx.RequestError, httpx.TimeoutException):
        return ValidationResponse(
            valid=False,
            message="Could not reach your Apps Script URL. Make sure you copied the full URL ending in /exec.",
        )


async def _validate_gmail(
    body: StepValidationRequest, session: AsyncSession
) -> ValidationResponse:
    """Validate Gmail OAuth token exists and is valid."""
    try:
        creds = await asyncio.get_event_loop().run_in_executor(None, load_credentials)
        if creds is None:
            return ValidationResponse(
                valid=False,
                message="Gmail isn't authorized yet. Run the authorization script: open a terminal, navigate to the automator folder, and run 'python authorize_gmail.py'.",
            )
        if not creds.valid:
            return ValidationResponse(
                valid=False,
                message="Your Gmail authorization has expired. Run 'python authorize_gmail.py' again to refresh it.",
            )
        return ValidationResponse(valid=True, message="")
    except Exception:
        return ValidationResponse(
            valid=False,
            message="Gmail isn't authorized yet. Run the authorization script: open a terminal, navigate to the automator folder, and run 'python authorize_gmail.py'.",
        )


async def _validate_profile(
    body: StepValidationRequest, session: AsyncSession
) -> ValidationResponse:
    """Validate profile fields are non-empty after trimming."""
    required_fields = {
        "full_name": "Full Name",
        "email": "Email",
        "phone": "Phone Number",
        "work_auth": "Work Authorization",
    }
    missing = []
    for key, label in required_fields.items():
        value = body.data.get(key, "")
        if not isinstance(value, str) or not value.strip():
            missing.append(label)

    if missing:
        return ValidationResponse(
            valid=False,
            message=f"Please fill in: {', '.join(missing)}.",
        )
    return ValidationResponse(valid=True, message="")


async def _validate_goals(
    body: StepValidationRequest, session: AsyncSession
) -> ValidationResponse:
    """Validate goals profile has minimum required configuration."""
    target_titles = body.data.get("target_titles", [])
    career_objective = body.data.get("career_objective", "")

    if not target_titles or all(not t.strip() for t in target_titles):
        return ValidationResponse(
            valid=False,
            message="Add at least one target job title so the tool knows what to look for.",
        )
    if not isinstance(career_objective, str) or not career_objective.strip():
        return ValidationResponse(
            valid=False,
            message="Write a brief career objective so the AI understands your goals when scoring jobs.",
        )
    return ValidationResponse(valid=True, message="")


async def _validate_search(
    body: StepValidationRequest, session: AsyncSession
) -> ValidationResponse:
    """Validate search config has at least one query."""
    keywords = body.data.get("keywords", "")
    search_queries = body.data.get("search_queries", [])

    has_keywords = isinstance(keywords, str) and keywords.strip()
    has_queries = isinstance(search_queries, list) and any(
        isinstance(q, str) and q.strip() for q in search_queries
    )

    if not has_keywords and not has_queries:
        return ValidationResponse(
            valid=False,
            message="Add at least one search keyword or query so the tool knows what jobs to find.",
        )
    return ValidationResponse(valid=True, message="")
```

### 4. Backend: Pydantic Schemas

```python
# Added to automator/src/api/schemas.py

class SetupSteps(BaseModel):
    """Boolean completion state for each wizard step."""
    claude_api: bool = False
    google_apps_script: bool = False
    gmail: bool = False
    profile: bool = False
    goals: bool = False
    search: bool = False


class SetupStatusResponse(BaseModel):
    """Response for GET /setup/status."""
    complete: bool = False
    steps: SetupSteps = SetupSteps()


class ValidationResponse(BaseModel):
    """Response for POST /setup/validate/{step}."""
    valid: bool
    message: str


class StepValidationRequest(BaseModel):
    """Request body for POST /setup/validate/{step}."""
    data: dict = {}
```

### 5. Frontend: First-Run Gate (App.tsx)

The app's root component queries setup status on mount and conditionally renders either the wizard or the main application shell.

```typescript
// webapp/src/App.tsx (modified)

function App() {
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSetupStatus()
      .then(setSetupStatus)
      .catch(() => setSetupStatus({ complete: false, steps: defaultSteps }))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingScreen />;

  if (!setupStatus?.complete) {
    return <SetupWizard initialStatus={setupStatus} onComplete={handleComplete} />;
  }

  return <MainApp />;
}
```

### 6. Frontend: Setup Wizard Component

The wizard manages a 6-step sequential flow with local state for all collected data, validation state per step, and navigation controls.

```typescript
// webapp/src/components/SetupWizard.tsx

interface WizardState {
  currentStep: number;
  stepData: Record<string, Record<string, unknown>>;
  stepValidated: boolean[];
  validating: boolean;
  errorMessage: string | null;
}

const WIZARD_STEPS = [
  { key: "claude_api", title: "Claude API Key", description: "Connect to the AI that scores and tailors your applications" },
  { key: "google_apps_script", title: "Google Apps Script", description: "Connect to your resume document" },
  { key: "gmail", title: "Gmail Notifications", description: "Get text alerts when the tool needs your attention" },
  { key: "profile", title: "Profile Info", description: "Your personal details for job applications" },
  { key: "goals", title: "Career Goals", description: "Tell the AI what kind of jobs you want" },
  { key: "search", title: "Search Config", description: "Define what jobs to search for" },
] as const;
```

**Wizard behavior:**
- On mount, reads `initialStatus.steps` to determine which steps are already complete. Sets `currentStep` to the index of the first incomplete step.
- Each step renders its own form fields. Data is stored in `stepData[stepKey]`.
- "Next" button triggers `POST /api/setup/validate/{stepKey}` with the step's data.
- While validating: button shows spinner, is disabled.
- On validation success: mark step as validated, advance to next step.
- On validation failure: display `message` from response below the form fields.
- "Back" button navigates to previous step without clearing any data.
- After final step validates: call all `PUT /config/*` endpoints to persist, then show completion screen.

### 7. Frontend: Diagnostics Page

```typescript
// webapp/src/pages/Diagnostics.tsx

interface DiagnosticResult {
  service: string;
  healthy: boolean;
  guidance: string | null;
}

const SERVICE_GUIDANCE: Record<string, string> = {
  claude_api: "Claude API is unreachable. Check your internet connection, or verify your API key in Settings.",
  gmail: "Gmail notifications are down. Your OAuth token may have expired — run 'python authorize_gmail.py' in the automator folder to refresh it.",
  google_docs: "Google Docs connection failed. Re-deploy your Apps Script and update the URL in Settings.",
};
```

The Diagnostics page:
- Shows a "Run Diagnostics" button.
- On click, calls `GET /api/health`.
- Displays each service with a green checkmark (pass) or red X (fail).
- For each failing service, renders a remediation guidance block with the service name, error description, and step-by-step fix instructions.
- When all pass, shows "All systems are working correctly."
- The "Run Diagnostics" button remains available for re-running after fixes.

### 8. Frontend: Dashboard Health Banners

The existing Dashboard component is extended with an inline alert system that reads from the health check response (already fetched for the status display).

```typescript
// webapp/src/components/HealthBanner.tsx

interface HealthBannerProps {
  health: { claude_api: boolean; gmail: boolean; google_docs: boolean };
}

function HealthBanner({ health }: HealthBannerProps) {
  const alerts = [];
  if (!health.claude_api) alerts.push(SERVICE_GUIDANCE.claude_api);
  if (!health.gmail) alerts.push(SERVICE_GUIDANCE.gmail);
  if (!health.google_docs) alerts.push(SERVICE_GUIDANCE.google_docs);

  if (alerts.length === 0) return null;

  return (
    <div className="space-y-2">
      {alerts.map((msg, i) => (
        <div key={i} className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <span className="font-medium">⚠️ </span>{msg}
        </div>
      ))}
    </div>
  );
}
```

---

## Data Models

### New Pydantic Schemas (Backend)

| Schema | Fields | Purpose |
|---|---|---|
| `SetupSteps` | `claude_api`, `google_apps_script`, `gmail`, `profile`, `goals`, `search` (all `bool`) | Per-step completion state |
| `SetupStatusResponse` | `complete: bool`, `steps: SetupSteps` | Response for `GET /setup/status` |
| `ValidationResponse` | `valid: bool`, `message: str` | Response for `POST /setup/validate/{step}` |
| `StepValidationRequest` | `data: dict` | Request body for validation (flexible dict per step) |

### Frontend Types (TypeScript)

```typescript
// webapp/src/types/setup.ts

interface SetupSteps {
  claude_api: boolean;
  google_apps_script: boolean;
  gmail: boolean;
  profile: boolean;
  goals: boolean;
  search: boolean;
}

interface SetupStatus {
  complete: boolean;
  steps: SetupSteps;
}

interface ValidationResult {
  valid: boolean;
  message: string;
}
```

### No Database Changes

No new tables or columns are needed. The wizard reads and writes through the existing `config` table using the same keys (`settings`, `goals_profile`, `user_profile`, `search_config`). The `GET /setup/status` endpoint derives completion state by inspecting these existing config values.

---

## API Design

### New Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/setup/status` | None | Returns setup completion state for all 6 steps |
| `POST` | `/setup/validate/{step}` | None | Validates a single step with live checks |

### `GET /setup/status` Response

```json
{
  "complete": false,
  "steps": {
    "claude_api": true,
    "google_apps_script": false,
    "gmail": false,
    "profile": false,
    "goals": false,
    "search": false
  }
}
```

### `POST /setup/validate/{step}` Request/Response

**Request:**
```json
{
  "data": {
    "claude_api_key": "sk-ant-api03-..."
  }
}
```

**Success Response:**
```json
{
  "valid": true,
  "message": ""
}
```

**Failure Response:**
```json
{
  "valid": false,
  "message": "This API key was rejected by Anthropic. Double-check that you copied the full key starting with sk-ant-."
}
```

### nginx Configuration Addition

The setup endpoints must be proxied without auth. Since nginx already proxies all `/api/*` to the automator, no nginx changes are needed — the auth bypass is handled at the FastAPI level (the setup routes simply don't include the `verify_token` dependency).

---

## Error Handling

### Validation Timeout

All connectivity-based validation steps (Claude API, GAS URL, Gmail) are wrapped in `asyncio.wait_for(timeout=10.0)`. If the check exceeds 10 seconds:
- The endpoint returns `{ "valid": false, "message": "This check is taking too long. Check your internet connection and try again." }`
- The frontend re-enables the "Next" button so the user can retry.

### Network Errors During Wizard

If the frontend cannot reach the backend at all (nginx returns 502 or network error):
- The wizard displays a connection error banner: "Cannot connect to the application backend. Make sure Docker is running."
- The "Next" button is re-enabled for retry.
- No data is lost — all wizard state is held in React component state.

### Partial Setup Recovery

If the user closes the browser mid-wizard:
- Steps that were already validated and persisted (via `PUT /config/*` at the end) are NOT persisted mid-flow. The wizard only persists on final completion.
- However, if the user previously completed setup and is re-running the wizard (e.g., after a config reset), `GET /setup/status` will correctly report which steps still have valid data.
- Design decision: we persist each step's data immediately after validation passes (not just at the end). This way, if the user closes the browser after Step 4, Steps 1-4 are saved and they can resume from Step 5.

### Health Check Failures on Dashboard

- Health check failures are non-blocking — the Dashboard still renders all other content.
- The alert banner appears at the top of the Dashboard, above the stats cards.
- Banners auto-dismiss on the next successful health poll (every 30 seconds via the existing polling hook).

---

## Security Considerations

### Unauthenticated Setup Endpoints

The `GET /setup/status` and `POST /setup/validate/{step}` endpoints are intentionally unauthenticated because:
1. On first run, no API token exists yet (it's generated on Automator startup but the user hasn't configured it in the frontend).
2. The setup endpoints are bound to `127.0.0.1` only (via nginx and Docker), so they're not network-accessible.
3. The validation endpoints accept configuration data but only use it for live checks — they don't persist anything. Persistence happens through the authenticated `PUT /config/*` endpoints.

**Risk mitigation:**
- The setup endpoints do not expose any stored secrets or configuration data.
- `GET /setup/status` returns only boolean flags, not actual config values.
- `POST /setup/validate/{step}` accepts data, performs a check, and returns pass/fail. The submitted data is not stored.
- Rate limiting: the 10-second timeout per request naturally limits abuse. No additional rate limiting is needed for localhost-only endpoints.

### Wizard Data Persistence

When the wizard persists data after each validated step, it calls the authenticated `PUT /config/*` endpoints. The API token is available because it's generated on Automator startup and stored in the config table. The frontend reads it from the `GET /setup/status` flow — wait, that endpoint doesn't return the token.

**Resolution:** The wizard persists step data by calling `PUT /config/*` endpoints. For the first step (Claude API key), the frontend needs the API token. The token is auto-generated on Automator startup and logged to stdout. The user enters it in the Token Prompt (existing Wave 0 flow). However, since the wizard gates the app before the Token Prompt, we need a different approach:

**Revised approach:** The setup validation endpoints also handle persistence. After validation passes, the endpoint persists the validated data directly (server-side). This eliminates the need for the frontend to call authenticated config endpoints during the wizard flow.

```python
async def _validate_claude_api(body: StepValidationRequest, session: AsyncSession) -> ValidationResponse:
    # ... validation logic ...
    if valid:
        # Persist immediately on successful validation
        settings = await get_config(session, "settings") or {}
        settings["claude_api_key"] = api_key
        await set_config(session, "settings", settings)
    return result
```

This keeps the wizard flow entirely unauthenticated while still persisting data securely (the backend validates before storing).

---

## Testing Strategy

### Unit Tests (Python — pytest)

- `_validate_profile`: various combinations of empty/whitespace/valid fields
- `_validate_goals`: empty target_titles, empty career_objective, valid combos
- `_validate_search`: empty keywords + empty queries, valid keywords, valid queries
- `_check_gmail_token_exists`: file present/absent
- `_profile_fields_complete`: field completeness logic
- `_goals_minimum_met`: minimum config logic
- Setup status `complete` derivation from step booleans

### Unit Tests (TypeScript — Vitest)

- Wizard step navigation logic (advance, back, skip to first incomplete)
- Health banner rendering based on health response
- Diagnostics result rendering
- First-run gate conditional rendering

### Integration Tests (Python — pytest + httpx)

- `GET /setup/status` returns correct structure with no auth
- `POST /setup/validate/claude_api` with mocked httpx (success, 401, timeout)
- `POST /setup/validate/google_apps_script` with mocked httpx (200, 401, unreachable)
- `POST /setup/validate/gmail` with mocked credentials loader
- `POST /setup/validate/profile` with various field combinations
- `POST /setup/validate/goals` with various field combinations
- `POST /setup/validate/search` with various field combinations
- Unknown step returns 404

### Property-Based Tests (Python — Hypothesis)

Property-based tests use **Hypothesis** with a minimum of 100 iterations per property. Each test references its design document property.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*


### Property 1: Wizard Progression Gating

*For any* wizard step and any validation result, the wizard SHALL advance to the next step if and only if the validation endpoint returns `valid: true`. If the endpoint returns `valid: false`, the wizard SHALL remain on the current step and the step SHALL NOT be marked as complete.

**Validates: Requirements 1.2**

### Property 2: Validation Error Message Passthrough

*For any* validation failure response containing a non-empty `message` string, the wizard SHALL display that exact message string to the user without modification, truncation, or reformatting.

**Validates: Requirements 1.4, 10.5**

### Property 3: Back Navigation Data Preservation

*For any* wizard state where the user is on step N (where N > 1) and has entered data in steps 1 through N, navigating back to any step M (where M < N) SHALL preserve all data entered in every step — no field values are cleared or modified by the navigation action.

**Validates: Requirements 1.6**

### Property 4: Claude API Validation Status Mapping

*For any* HTTP response received from the Anthropic API models endpoint during Claude API key validation: if the status code is 401, the validator SHALL return `valid: false` with the rejected-key message; if the status code is >= 500 or the request times out, the validator SHALL return `valid: false` with the unreachable message; for any other status code (2xx, 3xx, 4xx excluding 401), the validator SHALL return `valid: true`.

**Validates: Requirements 2.3, 2.4, 2.5**

### Property 5: Google Apps Script Validation Status Mapping

*For any* HTTP response received from the provided Google Apps Script URL during validation: if the status code is 200, the validator SHALL return `valid: true`; if the status code is 401 or the response body contains an authorization error, the validator SHALL return `valid: false` with the authorization message; if the request is unreachable or times out, the validator SHALL return `valid: false` with the unreachable message.

**Validates: Requirements 3.3, 3.4, 3.5**

### Property 6: Profile Field Completeness Validation

*For any* combination of profile field values (full_name, email, phone, work_auth), the profile validation endpoint SHALL return `valid: true` if and only if all four fields are non-empty strings after trimming whitespace. When validation fails, the error message SHALL list exactly the fields that are empty or whitespace-only — no more, no fewer.

**Validates: Requirements 5.2, 5.3, 5.4**

### Property 7: Goals Minimum Configuration Validation

*For any* goals profile data, the goals validation endpoint SHALL return `valid: true` if and only if the `target_titles` list contains at least one non-empty string AND the `career_objective` field is a non-empty string after trimming. When `target_titles` is empty, the error message SHALL reference target titles. When `career_objective` is empty, the error message SHALL reference career objective.

**Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.6**

### Property 8: Search Config Validation

*For any* search configuration data, the search validation endpoint SHALL return `valid: true` if and only if at least one of the following is true: (a) the `keywords` field is a non-empty string after trimming, or (b) the `search_queries` list contains at least one non-empty string after trimming.

**Validates: Requirements 7.2, 7.3, 7.4**

### Property 9: First-Run Gate Rendering

*For any* setup status response, the web app SHALL render the Setup Wizard as the only accessible UI if and only if `complete` is `false`. When `complete` is `true`, the web app SHALL render the normal application UI with all pages accessible.

**Validates: Requirements 8.2, 8.3**

### Property 10: Setup Status Completeness Derivation

*For any* combination of the 6 step boolean values in the setup status response, the top-level `complete` field SHALL equal the logical AND of all 6 step booleans — `complete` is `true` only when every step boolean is `true`, and `false` if any step boolean is `false`.

**Validates: Requirements 9.2, 9.3**

### Property 11: Validation Response Structure Consistency

*For any* call to `POST /setup/validate/{step}` (for any valid step name and any request body), the response SHALL contain exactly two fields: `valid` (boolean) and `message` (string). When `valid` is `true`, `message` SHALL be an empty string. When `valid` is `false`, `message` SHALL be a non-empty string.

**Validates: Requirements 10.3, 10.4, 10.5**

### Property 12: Validation Timeout Enforcement

*For any* validation step that involves a network call (claude_api, google_apps_script, gmail), if the underlying check does not complete within 10 seconds, the endpoint SHALL return `valid: false` with a timeout-specific error message rather than hanging indefinitely.

**Validates: Requirements 10.6**

### Property 13: Health State to Dashboard Banner Mapping

*For any* health check response where at least one service reports `false`, the Dashboard SHALL display an alert banner for each unhealthy service containing a plain-English description and remediation action. When all services report `true`, the Dashboard SHALL display zero alert banners.

**Validates: Requirements 11.1, 11.2, 11.6**
