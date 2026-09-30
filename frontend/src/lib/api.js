/**
 * Tiny fetch wrapper for the Django API.
 *  - same-origin cookies (session) on every call
 *  - CSRF: fetches the csrftoken cookie once, then echoes it in X-CSRFToken on
 *    every state-changing request (re-reading the cookie each time, because
 *    logging in rotates it), and retries once if Django says the token was stale
 *  - errors are normalised into ApiError { status, code, message, fields, retryAfter }
 */
export class ApiError extends Error {
  constructor({ status, code, message, fields, retryAfter, extra }) {
    super(message || "Something went wrong. Try again.");
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields || {};
    this.retryAfter = retryAfter ?? null;
    this.extra = extra || {};
  }
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
let unauthorizedHandler = null;

/** Called when a request comes back "not signed in" (e.g. the session expired). */
export function onUnauthorized(handler) {
  unauthorizedHandler = handler;
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null;
  };
}

export function readCookie(name) {
  const match = document.cookie.split("; ").find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

async function ensureCsrf(force = false) {
  if (!force && readCookie("csrftoken")) return;
  await fetch("/api/auth/csrf", { credentials: "same-origin", headers: { Accept: "application/json" } });
}

async function send(path, { method, body, signal }, attempt) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method)) {
    await ensureCsrf(attempt > 0);
    const token = readCookie("csrftoken");
    if (token) headers["X-CSRFToken"] = token;
  }

  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      credentials: "same-origin",
      signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: "Can't reach the server. Check your connection and try again.",
    });
  }

  if (response.status === 204) return null;
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* empty or non-JSON body */
  }
  if (response.ok) return data;

  const error = data?.error ?? {};
  if (response.status === 403 && /^CSRF/i.test(error.message || "") && attempt === 0) {
    return send(path, { method, body, signal }, 1);
  }
  const headerRetry = Number(response.headers?.get?.("Retry-After")) || null;
  const apiError = new ApiError({
    status: response.status,
    code: error.code || "error",
    message: error.message,
    fields: error.fields,
    retryAfter: error.retry_after ?? headerRetry,
    extra: error,
  });
  if (response.status === 403 && apiError.code === "not_authenticated") unauthorizedHandler?.();
  throw apiError;
}

export const api = {
  get: (path, options = {}) => send(path, { method: "GET", ...options }, 0),
  post: (path, body = {}, options = {}) => send(path, { method: "POST", body, ...options }, 0),
  patch: (path, body = {}, options = {}) => send(path, { method: "PATCH", body, ...options }, 0),
  delete: (path, options = {}) => send(path, { method: "DELETE", ...options }, 0),
};

/** First message for a field from a validation error, if any. */
export function fieldError(error, field) {
  const messages = error?.fields?.[field];
  return Array.isArray(messages) ? messages[0] : messages || null;
}
