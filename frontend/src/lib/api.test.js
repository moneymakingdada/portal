import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, fieldError, onUnauthorized, readCookie } from "./api";

function mockFetchOnce(status, body, headers = {}) {
  global.fetch.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    headers: { get: (name) => headers[name] ?? null },
  });
}

beforeEach(() => {
  global.fetch = vi.fn();
  // Most tests care about the real request, not the CSRF preamble, so start
  // with a token already "cached" and let the CSRF-specific tests override this.
  document.cookie = "csrftoken=cached-token; path=/";
});
afterEach(() => vi.restoreAllMocks());

describe("readCookie", () => {
  it("reads a named cookie", () => {
    document.cookie = "csrftoken=abc123; path=/";
    expect(readCookie("csrftoken")).toBe("abc123");
  });
  it("returns null when missing", () => {
    expect(readCookie("nope")).toBeNull();
  });
});

describe("api.get", () => {
  it("does not fetch a CSRF token for a GET", async () => {
    mockFetchOnce(200, { ok: true });
    await api.get("/auth/me");
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith("/api/auth/me", expect.objectContaining({ method: "GET" }));
  });

  it("returns null for a 204", async () => {
    mockFetchOnce(204, null);
    expect(await api.get("/auth/me")).toBeNull();
  });
});

describe("api.post CSRF handling", () => {
  it("fetches a token first when none is cached, then sends it", async () => {
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    // The server sets the cookie as a side effect of answering this request,
    // just like a real Set-Cookie header would when the browser fetches it.
    global.fetch.mockImplementationOnce(async () => {
      document.cookie = "csrftoken=tok-1; path=/";
      return { ok: true, status: 200, json: async () => ({}), headers: { get: () => null } };
    });
    mockFetchOnce(200, { ok: true });                          // the real POST
    await api.post("/auth/login", { email: "a@b.com" });
    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(global.fetch.mock.calls[0][0]).toBe("/api/auth/csrf");
    expect(global.fetch.mock.calls[1][1].headers["X-CSRFToken"]).toBe("tok-1");
  });

  it("skips the extra fetch when a token is already cached", async () => {
    document.cookie = "csrftoken=tok-2; path=/";
    mockFetchOnce(200, { ok: true });
    await api.post("/auth/login", {});
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch.mock.calls[0][1].headers["X-CSRFToken"]).toBe("tok-2");
  });

  it("retries once on a stale-CSRF 403, then succeeds", async () => {
    document.cookie = "csrftoken=stale; path=/";
    mockFetchOnce(403, { error: { code: "permission_denied", message: "CSRF Failed: token expired" } });
    mockFetchOnce(200, {});                                     // re-fetch csrf
    document.cookie = "csrftoken=fresh; path=/";
    mockFetchOnce(200, { ok: true });                           // retried POST
    const result = await api.post("/auth/login", {});
    expect(result).toEqual({ ok: true });
    expect(global.fetch).toHaveBeenCalledTimes(3);
    expect(global.fetch.mock.calls[2][1].headers["X-CSRFToken"]).toBe("fresh");
  });

  it("does not loop forever if the retry also gets a CSRF 403", async () => {
    document.cookie = "csrftoken=stale; path=/";
    mockFetchOnce(403, { error: { code: "permission_denied", message: "CSRF Failed: token expired" } });
    mockFetchOnce(200, {});
    document.cookie = "csrftoken=still-stale; path=/";
    mockFetchOnce(403, { error: { code: "permission_denied", message: "CSRF Failed: token expired" } });
    await expect(api.post("/auth/login", {})).rejects.toMatchObject({ status: 403 });
    expect(global.fetch).toHaveBeenCalledTimes(3);
  });
});

describe("api error normalisation", () => {
  it("wraps a structured error", async () => {
    mockFetchOnce(400, { error: { code: "invalid_phone", message: "Not a valid Ghana mobile number." } });
    await expect(api.post("/v1/otp/send", {})).rejects.toMatchObject({
      status: 400, code: "invalid_phone", message: "Not a valid Ghana mobile number.",
    });
  });

  it("carries retry_after from the body, falling back to the header", async () => {
    mockFetchOnce(429, { error: { code: "cooldown", message: "wait", retry_after: 42 } });
    const err1 = await api.post("/v1/otp/send", {}).catch((e) => e);
    expect(err1.retryAfter).toBe(42);

    mockFetchOnce(429, { error: { code: "cooldown", message: "wait" } }, { "Retry-After": "17" });
    const err2 = await api.post("/v1/otp/send", {}).catch((e) => e);
    expect(err2.retryAfter).toBe(17);
  });

  it("falls back to a network_error when fetch throws", async () => {
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(api.get("/auth/me")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("calls the unauthorized handler on a not_authenticated 403", async () => {
    const handler = vi.fn();
    const off = onUnauthorized(handler);
    mockFetchOnce(403, { error: { code: "not_authenticated", message: "nope" } });
    await api.get("/wallet").catch(() => {});
    expect(handler).toHaveBeenCalledTimes(1);
    off();
  });
});

describe("fieldError", () => {
  it("returns the first message for a field", () => {
    const error = new ApiError({ status: 400, code: "validation_error", fields: { phone: ["bad", "worse"] } });
    expect(fieldError(error, "phone")).toBe("bad");
  });
  it("returns null when the field has no error", () => {
    const error = new ApiError({ status: 400, code: "validation_error", fields: {} });
    expect(fieldError(error, "phone")).toBeNull();
    expect(fieldError(null, "phone")).toBeNull();
  });
});
