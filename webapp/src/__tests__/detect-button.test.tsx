/**
 * Unit tests for the LAN IP Detect button in the Settings component.
 *
 * Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { Settings } from "../pages/Settings";

// Mock the API client module
vi.mock("../api/client", () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  detectLanIp: vi.fn(),
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

import { getSettings, updateSettings, detectLanIp, ApiError } from "../api/client";

const mockGetSettings = vi.mocked(getSettings);
const mockUpdateSettings = vi.mocked(updateSettings);
const mockDetectLanIp = vi.mocked(detectLanIp);

const defaultSettings = {
  claude_api_key: null,
  gmail_user: null,
  sms_gateway: null,
  gdocs_script_url: null,
  good_fit_threshold: 70,
  stretch_threshold: 50,
  external_apply_threshold: 80,
  skip_viewed_jobs: true,
  backup_dir: null,
  dry_run: false,
};

/** Helper to render Settings and wait for initial load to complete */
async function renderSettings() {
  render(<Settings />);
  await waitFor(() => {
    expect(screen.getByText("Ntfy Notification Settings")).toBeInTheDocument();
  });
}

describe("Detect Button", () => {
  beforeEach(() => {
    mockGetSettings.mockResolvedValue(defaultSettings);
    mockUpdateSettings.mockResolvedValue(defaultSettings);
    mockDetectLanIp.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Validates: Requirement 2.1
   * THE Settings_UI SHALL display a "Detect" button adjacent to the LAN_IP_Field
   * within the ntfy configuration section.
   */
  it("renders the Detect button in the ntfy settings section", async () => {
    await renderSettings();

    const detectButton = screen.getByRole("button", { name: /detect/i });
    expect(detectButton).toBeInTheDocument();

    // Verify the LAN IP field is present
    const lanIpInput = screen.getByPlaceholderText("e.g., http://192.168.1.100:7432");
    expect(lanIpInput).toBeInTheDocument();
  });

  /**
   * Validates: Requirement 2.2
   * WHEN the user clicks the Detect button, THE Settings_UI SHALL call the
   * Detect_Endpoint and populate the LAN_IP_Field with the returned base URL.
   */
  it("populates the LAN IP field on successful detection", async () => {
    mockDetectLanIp.mockResolvedValue({
      lan_base_url: "http://192.168.1.42:7432",
      port: 7432,
    });

    await renderSettings();

    const detectButton = screen.getByRole("button", { name: /detect/i });
    fireEvent.click(detectButton);

    const lanIpInput = screen.getByPlaceholderText("e.g., http://192.168.1.100:7432") as HTMLInputElement;
    await waitFor(() => {
      expect(lanIpInput.value).toBe("http://192.168.1.42:7432");
    });
  });

  /**
   * Validates: Requirement 2.3
   * WHILE the detection request is in progress, THE Settings_UI SHALL display
   * a loading indicator on the Detect button and disable the button.
   */
  it("shows loading state: button disabled + spinner during request", async () => {
    // Create a promise that we control to keep the request pending
    let resolveDetect!: (value: { lan_base_url: string; port: number }) => void;
    mockDetectLanIp.mockImplementation(
      () => new Promise((resolve) => { resolveDetect = resolve; })
    );

    await renderSettings();

    const detectButton = screen.getByRole("button", { name: /detect/i });

    // Click the button to start detection
    fireEvent.click(detectButton);

    // Button should be disabled during loading
    await waitFor(() => {
      expect(detectButton).toBeDisabled();
    });

    // Spinner (svg with animate-spin class) should be present
    const spinner = detectButton.querySelector("svg.animate-spin");
    expect(spinner).toBeInTheDocument();

    // Resolve the promise to clean up
    await act(async () => {
      resolveDetect({ lan_base_url: "http://192.168.1.1:7432", port: 7432 });
    });

    // Button should be re-enabled after resolution
    expect(detectButton).not.toBeDisabled();
  });

  /**
   * Validates: Requirement 2.4
   * IF the Detect_Endpoint returns an error, THEN THE Settings_UI SHALL display
   * the error message inline beneath the LAN_IP_Field without clearing the
   * existing LAN_IP_Field value.
   */
  it("displays error inline and preserves existing field value", async () => {
    const errorMessage = "Auto-detection failed: could not resolve host.docker.internal within 5 seconds.";
    mockDetectLanIp.mockRejectedValue(
      new (ApiError as any)(503, "Service Unavailable", errorMessage)
    );

    await renderSettings();

    // Type a value into the LAN IP field first
    const lanIpInput = screen.getByPlaceholderText("e.g., http://192.168.1.100:7432") as HTMLInputElement;
    fireEvent.change(lanIpInput, { target: { value: "http://10.0.0.5:7432" } });
    expect(lanIpInput.value).toBe("http://10.0.0.5:7432");

    // Click detect
    const detectButton = screen.getByRole("button", { name: /detect/i });
    fireEvent.click(detectButton);

    // Error message should be displayed
    await waitFor(() => {
      expect(screen.getByText(errorMessage)).toBeInTheDocument();
    });

    // Existing field value should be preserved
    expect(lanIpInput.value).toBe("http://10.0.0.5:7432");
  });

  /**
   * Validates: Requirement 2.3 (timeout portion)
   * IF the detection request does not complete within 10 seconds, THEN THE
   * Settings_UI SHALL abort the request and display an error message.
   */
  it("shows timeout error after 10 seconds", async () => {
    vi.useFakeTimers();

    // Simulate a request that never resolves, so the AbortController fires
    mockDetectLanIp.mockImplementation((signal?: AbortSignal) => {
      return new Promise((_resolve, reject) => {
        if (signal) {
          signal.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted.", "AbortError"));
          });
        }
      });
    });

    // Render and wait for initial load (getSettings resolves via microtask)
    await act(async () => {
      render(<Settings />);
    });

    const detectButton = screen.getByRole("button", { name: /detect/i });

    await act(async () => {
      fireEvent.click(detectButton);
    });

    // Button should be disabled while loading
    expect(detectButton).toBeDisabled();

    // Advance timers by 10 seconds to trigger the AbortController timeout
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });

    // Timeout error message should be displayed
    expect(
      screen.getByText("Detection timed out. Please try again or enter your LAN IP manually.")
    ).toBeInTheDocument();

    // Button should be re-enabled
    expect(detectButton).not.toBeDisabled();

    vi.useRealTimers();
  });

  /**
   * Validates: Requirement 2.5
   * WHEN detection succeeds, THE Settings_UI SHALL NOT auto-save the ntfy
   * configuration — the user must still click "Save Ntfy Settings" to persist.
   */
  it("does not trigger save API call on successful detection", async () => {
    mockDetectLanIp.mockResolvedValue({
      lan_base_url: "http://192.168.1.99:7432",
      port: 7432,
    });

    await renderSettings();

    const detectButton = screen.getByRole("button", { name: /detect/i });
    fireEvent.click(detectButton);

    // Verify the field was populated
    const lanIpInput = screen.getByPlaceholderText("e.g., http://192.168.1.100:7432") as HTMLInputElement;
    await waitFor(() => {
      expect(lanIpInput.value).toBe("http://192.168.1.99:7432");
    });

    // updateSettings should NOT have been called
    expect(mockUpdateSettings).not.toHaveBeenCalled();
  });
});
