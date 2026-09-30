export const APP_NAME = import.meta.env.VITE_APP_NAME || "Portal";

/** Base URL shown in code samples, e.g. https://example.com/api/v1 */
export function publicApiBase() {
  const origin = import.meta.env.VITE_PUBLIC_API_URL || (typeof window !== "undefined" ? window.location.origin : "");
  return `${origin.replace(/\/$/, "")}/api/v1`;
}
