import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { useCheckout } from "./checkout";
import { redirectTo } from "./navigate";

vi.mock("./navigate", () => ({ redirectTo: vi.fn() }));
vi.mock("./api", () => ({ api: { post: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.restoreAllMocks());

describe("useCheckout", () => {
  it("posts the payload and redirects to the returned URL", async () => {
    api.post.mockResolvedValue({ authorization_url: "https://paystack.test/pay/abc" });
    const { result } = renderHook(() => useCheckout());

    await act(async () => result.current.start({ amount: "50" }, "custom"));

    expect(api.post).toHaveBeenCalledWith("/wallet/topup", { amount: "50" });
    expect(redirectTo).toHaveBeenCalledWith("https://paystack.test/pay/abc");
  });

  it("marks only the button that was clicked as busy, and stays busy through redirect", async () => {
    let resolve;
    api.post.mockReturnValue(new Promise((r) => { resolve = r; }));
    const { result } = renderHook(() => useCheckout());

    let promise;
    act(() => { promise = result.current.start({ plan_id: 7 }, 7); });
    expect(result.current.busyKey).toBe(7);

    await act(async () => {
      resolve({ authorization_url: "https://paystack.test/pay/xyz" });
      await promise;
    });
    expect(result.current.busyKey).toBe(7);   // redirecting away: never explicitly cleared
  });

  it("clears busy and surfaces the error on failure", async () => {
    const error = new Error("Wallet balance is too low.");
    api.post.mockRejectedValue(error);
    const { result } = renderHook(() => useCheckout());

    await act(async () => result.current.start({ amount: "5" }, "custom"));

    expect(result.current.busyKey).toBeNull();
    expect(result.current.error).toBe(error);
    expect(redirectTo).not.toHaveBeenCalled();
  });

  it("a later successful call clears an earlier error", async () => {
    api.post.mockRejectedValueOnce(new Error("nope"));
    const { result } = renderHook(() => useCheckout());
    await act(async () => result.current.start({ amount: "5" }, "custom"));
    expect(result.current.error).not.toBeNull();

    api.post.mockResolvedValueOnce({ authorization_url: "https://paystack.test/pay/2" });
    await act(async () => result.current.start({ amount: "5" }, "custom"));
    expect(result.current.error).toBeNull();
  });

  it("resets busy if the browser restores the page from cache (Back button after paying)", async () => {
    api.post.mockReturnValue(new Promise(() => {})); // never resolves; simulates the page unloading instead
    const { result } = renderHook(() => useCheckout());

    act(() => { result.current.start({ amount: "5" }, "custom"); });
    expect(result.current.busyKey).toBe("custom");

    act(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })));
    await waitFor(() => expect(result.current.busyKey).toBeNull());
  });

  it("a plain (non-cached) pageshow leaves a real in-flight request alone", async () => {
    api.post.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useCheckout());

    act(() => { result.current.start({ amount: "5" }, "custom"); });
    act(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: false })));

    expect(result.current.busyKey).toBe("custom");
  });
});
