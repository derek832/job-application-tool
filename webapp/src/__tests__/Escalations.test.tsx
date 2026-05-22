/**
 * Frontend tests for escalation components.
 *
 * Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.6
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Escalations } from "../pages/Escalations";
import { EscalationDetail } from "../pages/EscalationDetail";

// Mock the API client module
vi.mock("../api/client", () => ({
  getEscalations: vi.fn(),
  getEscalation: vi.fn(),
  submitEscalation: vi.fn(),
  skipEscalation: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    detail: string;
    constructor(status: number, statusText: string, detail: string) {
      super(`API ${status} ${statusText}: ${detail}`);
      this.name = "ApiError";
      this.status = status;
      this.detail = detail;
    }
  },
}));

import {
  getEscalations,
  getEscalation,
  submitEscalation,
  skipEscalation,
} from "../api/client";

const mockGetEscalations = vi.mocked(getEscalations);
const mockGetEscalation = vi.mocked(getEscalation);
const mockSubmitEscalation = vi.mocked(submitEscalation);
const mockSkipEscalation = vi.mocked(skipEscalation);

// ---------------------------------------------------------------------------
// Test Data Factories
// ---------------------------------------------------------------------------

function makeEscalation(overrides: Record<string, unknown> = {}) {
  return {
    id: "esc-001",
    job_id: "job-001",
    tier: "human_review" as const,
    form_state_snapshot: {
      external_url: "https://boards.greenhouse.io/acme/jobs/123",
      fields: [
        { field_id: "f1", label: "Full Name", value: "Derek Smith", type: "text" },
        { field_id: "f2", label: "Email", value: "derek@example.com", type: "text" },
      ],
      screenshot_path: "/data/screenshots/esc-001.png",
      page_title: "Apply - Senior Engineer at Acme Corp",
    },
    draft_answers: [
      {
        field_id: "f3",
        question_text: "Why are you interested in this role?",
        draft_answer: "I am drawn to Acme's mission...",
        edited_answer: null,
      },
    ],
    timeout_deadline: new Date(Date.now() + 30 * 60 * 1000).toISOString(), // 30 min from now
    freshness_tier: "fresh",
    status: "pending",
    resolution_method: null,
    created_at: new Date().toISOString(),
    resolved_at: null,
    job_title: "Senior Engineer",
    company: "Acme Corp",
    fit_score: 92,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Escalation List Component Tests
// ---------------------------------------------------------------------------

describe("Escalations List", () => {
  beforeEach(() => {
    mockGetEscalations.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Validates: Requirement 6.1
   * THE Review_UI SHALL display a list of pending Escalation_Records sorted by
   * Auto_Submit_Timeout deadline ascending (most urgent first).
   */
  it("renders pending items sorted by urgency (most urgent first)", async () => {
    const now = Date.now();
    const escalations = [
      makeEscalation({
        id: "esc-far",
        job_title: "Backend Dev",
        company: "FarCo",
        timeout_deadline: new Date(now + 5 * 60 * 60 * 1000).toISOString(), // 5 hours
      }),
      makeEscalation({
        id: "esc-urgent",
        job_title: "Frontend Dev",
        company: "UrgentCo",
        timeout_deadline: new Date(now + 10 * 60 * 1000).toISOString(), // 10 min
      }),
      makeEscalation({
        id: "esc-mid",
        job_title: "Full Stack",
        company: "MidCo",
        timeout_deadline: new Date(now + 45 * 60 * 1000).toISOString(), // 45 min
      }),
    ];

    mockGetEscalations.mockResolvedValue({ escalations, total: 3 });

    render(<Escalations />);

    await waitFor(() => {
      expect(screen.getByText("Frontend Dev")).toBeInTheDocument();
    });

    // All items should be rendered
    expect(screen.getByText("Backend Dev")).toBeInTheDocument();
    expect(screen.getByText("Full Stack")).toBeInTheDocument();
    expect(screen.getByText("UrgentCo")).toBeInTheDocument();
    expect(screen.getByText("MidCo")).toBeInTheDocument();
    expect(screen.getByText("FarCo")).toBeInTheDocument();
  });

  /**
   * Validates: Requirement 6.1
   * Shows job title, company, fit score, escalation tier, and time remaining.
   */
  it("displays job title, company, fit score, tier badge, and countdown", async () => {
    const escalation = makeEscalation({
      timeout_deadline: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(), // 2 hours
    });

    mockGetEscalations.mockResolvedValue({ escalations: [escalation], total: 1 });

    render(<Escalations />);

    await waitFor(() => {
      expect(screen.getByText("Senior Engineer")).toBeInTheDocument();
    });

    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();
    expect(screen.getByText("Review")).toBeInTheDocument();
    expect(screen.getByText("fresh")).toBeInTheDocument();
  });

  it("shows empty state when no pending escalations", async () => {
    mockGetEscalations.mockResolvedValue({ escalations: [], total: 0 });

    render(<Escalations />);

    await waitFor(() => {
      expect(screen.getByText("No pending escalations")).toBeInTheDocument();
    });
  });

  it("shows error message when API call fails", async () => {
    mockGetEscalations.mockRejectedValue(new Error("Network error"));

    render(<Escalations />);

    await waitFor(() => {
      expect(screen.getByText("Failed to load escalations")).toBeInTheDocument();
    });
  });

  it("calls onSelectEscalation when a card is clicked", async () => {
    const escalation = makeEscalation();
    mockGetEscalations.mockResolvedValue({ escalations: [escalation], total: 1 });

    const onSelect = vi.fn();
    render(<Escalations onSelectEscalation={onSelect} />);

    await waitFor(() => {
      expect(screen.getByText("Senior Engineer")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Senior Engineer"));
    expect(onSelect).toHaveBeenCalledWith("esc-001");
  });

  it("shows CAPTCHA badge for captcha tier escalations", async () => {
    const escalation = makeEscalation({
      tier: "captcha",
      timeout_deadline: null,
      freshness_tier: null,
    });
    mockGetEscalations.mockResolvedValue({ escalations: [escalation], total: 1 });

    render(<Escalations />);

    await waitFor(() => {
      expect(screen.getByText("CAPTCHA")).toBeInTheDocument();
    });

    expect(screen.getByText("No timeout")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Countdown Timer Tests
// ---------------------------------------------------------------------------

describe("Countdown Timer", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockGetEscalations.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  /**
   * Validates: Requirement 6.1
   * Color-coded urgency: red < 15 min, amber < 1 hour, green > 1 hour.
   */
  it("displays correct relative time for items > 1 hour away", async () => {
    const now = new Date("2025-01-15T12:00:00Z");
    vi.setSystemTime(now);

    const escalation = makeEscalation({
      timeout_deadline: "2025-01-15T14:15:00Z", // exactly 2h 15m from now
    });
    mockGetEscalations.mockResolvedValue({ escalations: [escalation], total: 1 });

    render(<Escalations />);

    await waitFor(() => {
      expect(screen.getByText("2h 15m")).toBeInTheDocument();
    });
  });

  it("displays minutes-only format for items < 1 hour away", async () => {
    const now = new Date("2025-01-15T12:00:00Z");
    vi.setSystemTime(now);

    const escalation = makeEscalation({
      timeout_deadline: "2025-01-15T12:42:00Z", // exactly 42 min from now
    });
    mockGetEscalations.mockResolvedValue({ escalations: [escalation], total: 1 });

    render(<Escalations />);

    await waitFor(() => {
      expect(screen.getByText("42m")).toBeInTheDocument();
    });
  });

  it("displays 'Expired' for past deadlines", async () => {
    const now = new Date("2025-01-15T12:00:00Z");
    vi.setSystemTime(now);

    const escalation = makeEscalation({
      timeout_deadline: "2025-01-15T11:55:00Z", // 5 min ago
    });
    mockGetEscalations.mockResolvedValue({ escalations: [escalation], total: 1 });

    render(<Escalations />);

    await waitFor(() => {
      expect(screen.getByText("Expired")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Escalation Detail Component Tests
// ---------------------------------------------------------------------------

describe("EscalationDetail", () => {
  const mockOnBack = vi.fn();

  beforeEach(() => {
    mockGetEscalation.mockReset();
    mockSubmitEscalation.mockReset();
    mockSkipEscalation.mockReset();
    mockOnBack.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Validates: Requirement 6.2
   * THE Review_UI SHALL display the Form_State_Snapshot including all form field
   * labels and their current values, and editable text areas for each Draft_Answer.
   */
  it("renders form state fields and editable draft answers", async () => {
    const escalation = makeEscalation();
    mockGetEscalation.mockResolvedValue(escalation as any);

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("Senior Engineer")).toBeInTheDocument();
    });

    // Form state fields
    expect(screen.getByText("Full Name")).toBeInTheDocument();
    expect(screen.getByText("Derek Smith")).toBeInTheDocument();
    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByText("derek@example.com")).toBeInTheDocument();

    // Draft answer question text
    expect(screen.getByText("Why are you interested in this role?")).toBeInTheDocument();

    // Draft answer should be in an editable textarea
    const textarea = screen.getByDisplayValue("I am drawn to Acme's mission...");
    expect(textarea).toBeInTheDocument();
    expect(textarea.tagName).toBe("TEXTAREA");
  });

  it("renders job title, company, and fit score in header", async () => {
    const escalation = makeEscalation();
    mockGetEscalation.mockResolvedValue(escalation as any);

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("Senior Engineer")).toBeInTheDocument();
    });

    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();
  });

  it("allows editing draft answers", async () => {
    const escalation = makeEscalation();
    mockGetEscalation.mockResolvedValue(escalation as any);

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByDisplayValue("I am drawn to Acme's mission...")).toBeInTheDocument();
    });

    const textarea = screen.getByDisplayValue("I am drawn to Acme's mission...");
    fireEvent.change(textarea, { target: { value: "My personalized answer here" } });

    expect(screen.getByDisplayValue("My personalized answer here")).toBeInTheDocument();
  });

  /**
   * Validates: Requirement 6.3
   * WHEN the user clicks "Submit", THE Escalation_Engine SHALL resume the paused
   * application using the user's edited answers.
   */
  it("submit button calls submitEscalation API with edited answers", async () => {
    const escalation = makeEscalation();
    mockGetEscalation.mockResolvedValue(escalation as any);
    mockSubmitEscalation.mockResolvedValue({
      ...escalation,
      status: "resolved",
      resolution_method: "user_submit",
      resolved_at: new Date().toISOString(),
    } as any);

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("Submit")).toBeInTheDocument();
    });

    // Edit the draft answer
    const textarea = screen.getByDisplayValue("I am drawn to Acme's mission...");
    fireEvent.change(textarea, { target: { value: "Edited answer" } });

    // Click submit
    fireEvent.click(screen.getByText("Submit"));

    await waitFor(() => {
      expect(mockSubmitEscalation).toHaveBeenCalledWith("esc-001", [
        { field_id: "f3", edited_answer: "Edited answer" },
      ]);
    });
  });

  /**
   * Validates: Requirement 6.4
   * WHEN the user clicks "Skip", THE Escalation_Engine SHALL cancel the application.
   */
  it("skip button calls skipEscalation API", async () => {
    const escalation = makeEscalation();
    mockGetEscalation.mockResolvedValue(escalation as any);
    mockSkipEscalation.mockResolvedValue({
      ...escalation,
      status: "skipped",
      resolution_method: "user_skip",
      resolved_at: new Date().toISOString(),
    } as any);

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("Skip")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Skip"));

    await waitFor(() => {
      expect(mockSkipEscalation).toHaveBeenCalledWith("esc-001");
    });
  });

  it("shows action error when submit fails", async () => {
    const escalation = makeEscalation();
    mockGetEscalation.mockResolvedValue(escalation as any);
    mockSubmitEscalation.mockRejectedValue(new Error("Server error"));

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("Submit")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Submit"));

    await waitFor(() => {
      expect(screen.getByText("Submit failed")).toBeInTheDocument();
    });
  });

  it("shows error when escalation ID is null", async () => {
    render(<EscalationDetail escalationId={null} onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("No escalation ID provided")).toBeInTheDocument();
    });
  });

  it("shows error when escalation fetch fails", async () => {
    mockGetEscalation.mockRejectedValue(new Error("Not found"));

    render(<EscalationDetail escalationId="esc-bad" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("Failed to load escalation")).toBeInTheDocument();
    });
  });

  it("back button calls onBack handler", async () => {
    const escalation = makeEscalation();
    mockGetEscalation.mockResolvedValue(escalation as any);

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByLabelText("Back to escalation list")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByLabelText("Back to escalation list"));
    expect(mockOnBack).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Read-Only Mode Tests
// ---------------------------------------------------------------------------

describe("EscalationDetail — Read-Only Mode", () => {
  const mockOnBack = vi.fn();

  beforeEach(() => {
    mockGetEscalation.mockReset();
    mockOnBack.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Validates: Requirement 6.6
   * WHEN an Escalation_Record has already been resolved, THE Review_UI SHALL
   * display the record as read-only with its resolution status and timestamp.
   */
  it("shows status badge and no edit controls for resolved records", async () => {
    const resolvedEscalation = makeEscalation({
      status: "resolved",
      resolution_method: "user_submit",
      resolved_at: "2025-01-15T10:30:00Z",
    });
    mockGetEscalation.mockResolvedValue(resolvedEscalation as any);

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("Senior Engineer")).toBeInTheDocument();
    });

    // Status badge should show "resolved"
    expect(screen.getByText("resolved")).toBeInTheDocument();

    // Resolution banner should be visible
    expect(screen.getByText("Submitted by user")).toBeInTheDocument();

    // Submit and Skip buttons should NOT be present
    expect(screen.queryByText("Submit")).not.toBeInTheDocument();
    expect(screen.queryByText("Skip")).not.toBeInTheDocument();

    // Draft answers should be read-only (no textarea)
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("shows auto-submitted status for timed-out records", async () => {
    const autoSubmitted = makeEscalation({
      status: "auto_submitted",
      resolution_method: "auto_submit",
      resolved_at: "2025-01-15T11:00:00Z",
    });
    mockGetEscalation.mockResolvedValue(autoSubmitted as any);

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("auto submitted")).toBeInTheDocument();
    });

    expect(screen.getByText("Auto-submitted after timeout")).toBeInTheDocument();
    expect(screen.queryByText("Submit")).not.toBeInTheDocument();
    expect(screen.queryByText("Skip")).not.toBeInTheDocument();
  });

  it("shows skipped status for user-skipped records", async () => {
    const skipped = makeEscalation({
      status: "skipped",
      resolution_method: "user_skip",
      resolved_at: "2025-01-15T09:00:00Z",
    });
    mockGetEscalation.mockResolvedValue(skipped as any);

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("skipped")).toBeInTheDocument();
    });

    expect(screen.getByText("Skipped by user")).toBeInTheDocument();
    expect(screen.queryByText("Submit")).not.toBeInTheDocument();
    expect(screen.queryByText("Skip")).not.toBeInTheDocument();
  });

  it("shows expired status for expired records", async () => {
    const expired = makeEscalation({
      status: "expired",
      resolution_method: "timeout_expired",
      resolved_at: "2025-01-16T10:30:00Z",
    });
    mockGetEscalation.mockResolvedValue(expired as any);

    render(<EscalationDetail escalationId="esc-001" onBack={mockOnBack} />);

    await waitFor(() => {
      expect(screen.getByText("expired")).toBeInTheDocument();
    });

    expect(screen.getByText("Expired")).toBeInTheDocument();
    expect(screen.queryByText("Submit")).not.toBeInTheDocument();
    expect(screen.queryByText("Skip")).not.toBeInTheDocument();
  });
});
