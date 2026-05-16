/**
 * Property-based tests for API client and hooks.
 *
 * Uses fast-check with a minimum of 100 iterations per property.
 *
 * Validates: Requirements 4.1, 4.2, 4.4, 5.5, 6.2, 6.3
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as fc from "fast-check";
import { ApiError } from "../api/client";

// ---------------------------------------------------------------------------
// Property 4: API Client Request Isolation
// ---------------------------------------------------------------------------

describe("Property 4: API Client Request Isolation", () => {
  /**
   * **Validates: Requirements 4.1, 5.5**
   *
   * For any API client function call, the resulting HTTP request SHALL target
   * a URL with the relative path prefix `/api/` and SHALL NOT contain an
   * absolute URL or reference any host other than the current origin.
   */
  it("all request URLs use relative /api/ prefix", async () => {
    const capturedUrls: string[] = [];

    const mockFetch = vi.fn(async (url: string | URL | Request) => {
      capturedUrls.push(String(url));
      return new Response(JSON.stringify({ status: "idle", last_run_at: null, next_run_at: null, queue_count: 0, stats: { total_discovered: 0, total_applied: 0, total_skipped: 0, total_pending_review: 0, application_success_rate: 0 }, health: { claude_api: true, gmail: true, google_docs: true } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    vi.stubGlobal("fetch", mockFetch);

    // Mock localStorage to always have a token
    const mockStorage: Record<string, string> = { jat_api_token: "test-token" };
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => mockStorage[key] ?? null,
      setItem: (key: string, value: string) => { mockStorage[key] = value; },
      removeItem: (key: string) => { delete mockStorage[key]; },
    });

    // Import the client fresh for each test
    const client = await import("../api/client");

    // Define API functions that we can call to generate requests
    const apiCalls = [
      () => client.getStatus(),
      () => client.getHealth(),
      () => client.getQueue(),
      () => client.getJobs(),
      () => client.getJobStats(),
      () => client.getSearchConfig(),
      () => client.getGoalsProfile(),
      () => client.getUserProfile(),
      () => client.getSettings(),
    ];

    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 0, max: apiCalls.length - 1 }),
        async (idx) => {
          capturedUrls.length = 0;
          try {
            await apiCalls[idx]!();
          } catch {
            // Validation errors are fine — we care about the URL
          }

          for (const url of capturedUrls) {
            // Must start with /api/
            expect(url).toMatch(/^\/api\//);
            // Must NOT be an absolute URL (no protocol://)
            expect(url).not.toMatch(/^https?:\/\//);
          }
        },
      ),
      { numRuns: 100 },
    );

    vi.unstubAllGlobals();
  });
});

// ---------------------------------------------------------------------------
// Property 5: API Client Auth Header Inclusion
// ---------------------------------------------------------------------------

describe("Property 5: API Client Auth Header Inclusion", () => {
  /**
   * **Validates: Requirements 4.2**
   *
   * For any API client function call when a Bearer token is present in
   * localStorage, the resulting HTTP request SHALL include an
   * `Authorization: Bearer {token}` header where `{token}` is the exact
   * value stored in localStorage.
   */
  it("Authorization header matches stored token", async () => {
    const capturedHeaders: Record<string, string>[] = [];

    const mockFetch = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const headers = init?.headers as Record<string, string> | undefined;
      if (headers) {
        capturedHeaders.push({ ...headers });
      }
      return new Response(JSON.stringify({ status: "idle", last_run_at: null, next_run_at: null, queue_count: 0, stats: { total_discovered: 0, total_applied: 0, total_skipped: 0, total_pending_review: 0, application_success_rate: 0 }, health: { claude_api: true, gmail: true, google_docs: true } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    vi.stubGlobal("fetch", mockFetch);

    const client = await import("../api/client");

    // Generate arbitrary non-empty token strings
    const tokenArb = fc.string({ minLength: 1, maxLength: 200 }).filter(
      (s) => s.trim().length > 0,
    );

    await fc.assert(
      fc.asyncProperty(tokenArb, async (token) => {
        // Set the token in localStorage
        const mockStorage: Record<string, string> = { jat_api_token: token };
        vi.stubGlobal("localStorage", {
          getItem: (key: string) => mockStorage[key] ?? null,
          setItem: (key: string, value: string) => { mockStorage[key] = value; },
          removeItem: (key: string) => { delete mockStorage[key]; },
        });

        capturedHeaders.length = 0;

        try {
          await client.getStatus();
        } catch {
          // Validation errors are fine — we care about the header
        }

        expect(capturedHeaders.length).toBeGreaterThan(0);
        const authHeader = capturedHeaders[0]!["Authorization"];
        expect(authHeader).toBe(`Bearer ${token}`);
      }),
      { numRuns: 100 },
    );

    vi.unstubAllGlobals();
  });
});

// ---------------------------------------------------------------------------
// Property 6: API Error Mapping
// ---------------------------------------------------------------------------

describe("Property 6: API Error Mapping", () => {
  /**
   * **Validates: Requirements 4.4**
   *
   * For any non-2xx HTTP response from the Automator (status codes 400–599)
   * with a JSON body containing a `detail` field, the API client SHALL
   * produce an `ApiError` object where `status` equals the HTTP status code
   * and `detail` equals the value of the response body's `detail` field.
   */
  it("non-2xx responses produce correct ApiError objects", async () => {
    const client = await import("../api/client");

    // Arbitrary HTTP error status codes (400-599)
    const statusArb = fc.integer({ min: 400, max: 599 });
    // Arbitrary detail strings
    const detailArb = fc.string({ minLength: 1, maxLength: 500 });

    await fc.assert(
      fc.asyncProperty(statusArb, detailArb, async (status, detail) => {
        const mockFetch = vi.fn(async () => {
          return new Response(JSON.stringify({ detail }), {
            status,
            statusText: "Error",
            headers: { "Content-Type": "application/json" },
          });
        });

        vi.stubGlobal("fetch", mockFetch);

        const mockStorage: Record<string, string> = { jat_api_token: "test-token" };
        vi.stubGlobal("localStorage", {
          getItem: (key: string) => mockStorage[key] ?? null,
          setItem: (key: string, value: string) => { mockStorage[key] = value; },
          removeItem: (key: string) => { delete mockStorage[key]; },
        });

        try {
          await client.getStatus();
          // Should not reach here — the call should throw
          expect.fail("Expected ApiError to be thrown");
        } catch (err) {
          expect(err).toBeInstanceOf(ApiError);
          const apiErr = err as InstanceType<typeof ApiError>;
          expect(apiErr.status).toBe(status);
          expect(apiErr.detail).toBe(detail);
        }
      }),
      { numRuns: 100 },
    );

    vi.unstubAllGlobals();
  });
});

// ---------------------------------------------------------------------------
// Property 7: Tab Title Badge Formatting
// ---------------------------------------------------------------------------

describe("Property 7: Tab Title Badge Formatting", () => {
  let originalTitle: string;

  beforeEach(() => {
    originalTitle = document.title;
  });

  afterEach(() => {
    document.title = originalTitle;
  });

  /**
   * **Validates: Requirements 6.2, 6.3**
   *
   * For any non-negative integer queue count, the browser tab title SHALL be
   * formatted as `(N) Job Application Tool` when the count is greater than
   * zero, and as `Job Application Tool` (no prefix) when the count is zero.
   */
  it("title format for any non-negative integer count", async () => {
    const { renderHook, cleanup } = await import("@testing-library/react");
    const { useBadge } = await import("../hooks/useBadge");

    // Non-negative integers
    const countArb = fc.integer({ min: 0, max: 1_000_000 });

    fc.assert(
      fc.property(countArb, (count) => {
        const { unmount } = renderHook(() => useBadge(count));

        if (count > 0) {
          expect(document.title).toBe(`(${count}) Job Application Tool`);
        } else {
          expect(document.title).toBe("Job Application Tool");
        }

        unmount();
      }),
      { numRuns: 100 },
    );

    cleanup();
  });
});
