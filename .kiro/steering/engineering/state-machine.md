---
inclusion: manual
---

# Engineering — Job State Machine

## Purpose

Every job flows through a defined lifecycle. This document is the source of truth for valid states, transitions, and the rules governing them. If code contradicts this document, the code is wrong.

## Valid Statuses (12 total)

| Status | Meaning | Terminal? |
|--------|---------|-----------|
| `discovered` | Job card found on LinkedIn, basic metadata captured | No |
| `extracted` | Full description text extracted from the job detail panel | No |
| `extraction_failed` | Could not extract description (page load failure, DOM change) | Yes (retryable next run) |
| `scored` | Claude scored the job; awaiting routing or human review | No |
| `approved_for_apply` | Cleared for application (auto or human-approved) | No |
| `skipped` | Auto-skipped (low score, deal-breaker, or pre-filter) | Yes |
| `rejected_by_user` | User explicitly rejected from human queue | Yes |
| `resume_failed` | Resume tailoring or PDF export failed | Yes (retryable) |
| `applying` | Application in progress (form being filled) | No |
| `apply_failed` | Application submission failed (form error, CAPTCHA, timeout) | Yes (retryable) |
| `applied` | Application successfully submitted | Yes |
| `manually_applied` | User applied manually after notification | Yes |

## State Transition Diagram

```
discovered
    │
    ├─ extraction succeeds ──→ extracted
    │                              │
    │                              ├─ pre-filter fails ──→ skipped
    │                              │
    │                              ├─ scoring succeeds ──→ scored
    │                              │                         │
    │                              │                         ├─ good_fit (no boundary) ──→ approved_for_apply
    │                              │                         │                                    │
    │                              │                         │                                    ├─ tailoring succeeds ──→ applying
    │                              │                         │                                    │                            │
    │                              │                         │                                    │                            ├─ submit succeeds ──→ applied
    │                              │                         │                                    │                            │
    │                              │                         │                                    │                            └─ submit fails ──→ apply_failed
    │                              │                         │                                    │
    │                              │                         │                                    └─ tailoring fails ──→ resume_failed
    │                              │                         │
    │                              │                         ├─ stretch_role / boundary ──→ [human queue]
    │                              │                         │       │
    │                              │                         │       ├─ user approves ──→ approved_for_apply
    │                              │                         │       │
    │                              │                         │       ├─ user rejects ──→ rejected_by_user
    │                              │                         │       │
    │                              │                         │       └─ 48h timeout ──→ skipped
    │                              │                         │
    │                              │                         ├─ deal_breaker ──→ skipped
    │                              │                         │
    │                              │                         └─ low score ──→ skipped
    │                              │
    │                              └─ scoring fails ──→ (stays extracted, retried next run)
    │
    └─ extraction fails ──→ extraction_failed
```

## Transition Rules

### Hard Rules (enforced in code)

1. **Status can only move forward.** No job should ever go from `applied` back to `scored`. The `update_job_status` function validates against `VALID_STATUSES` but does not currently enforce ordering — this is enforced by pipeline logic.

2. **Every transition is audited.** A `StatusTransition` row is written for every status change with timestamp, from_status, to_status, and reason.

3. **Terminal states are final.** Jobs in `skipped`, `rejected_by_user`, `applied`, or `manually_applied` are never re-processed. They're done.

4. **Retryable failures are not re-entered automatically.** Jobs in `extraction_failed`, `resume_failed`, or `apply_failed` can be retried on the next pipeline run (they're queried by status), but only if the pipeline explicitly includes retry logic for that status.

### Soft Rules (design intent)

5. **One status change per pipeline stage.** Each stage function receives a job in a known status and moves it to exactly one new status. No stage should make multiple transitions.

6. **`applying` is a transient state.** A job should only be in `applying` for the duration of the form submission (seconds to minutes). If the pipeline crashes during `applying`, the next run should detect this and either retry or mark as `apply_failed`.

7. **Human queue is not a status.** It's a query: jobs with `status = 'scored'` AND `queue_reason IS NOT NULL`. The user's action (approve/reject) transitions the job out of `scored`.

8. **`manually_applied` requires user action.** This status is set via the API when the user confirms they applied manually after receiving a notification about a stuck job.

## Timestamps

Each status transition should update the corresponding timestamp column:

| Transition to | Timestamp column |
|---------------|-----------------|
| `extracted` | `extracted_at` |
| `scored` | `scored_at` |
| `approved_for_apply` | `approved_at` |
| `applied` | `applied_at` |
| Any status | `updated_at` |

## Adding New Statuses

If a new status is needed:
1. Add it to `VALID_STATUSES` in `src/db/models.py`
2. Update the test in `test_db_models.py` that asserts the count and set membership
3. Document it in this file with its meaning, terminal flag, and valid transitions
4. Add the transition to the diagram above
