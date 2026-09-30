import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { redirectTo } from "./navigate";

/** Start a Paystack payment and send the browser to its checkout page.
 *  `payload` is {plan_id} or {amount}; `key` names which button is busy. */
export function useCheckout() {
  const [busyKey, setBusyKey] = useState(null);
  const [error, setError] = useState(null);

  // Coming back with the browser's Back button restores this page as it was
  // (busy button and all), so undo that.
  useEffect(() => {
    const reset = (event) => {
      if (event.persisted) setBusyKey(null);
    };
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);

  const start = useCallback(async (payload, key = "default") => {
    setBusyKey(key);
    setError(null);
    try {
      const { authorization_url: url } = await api.post("/wallet/topup", payload);
      redirectTo(url);          // the page unloads; the button stays busy until it does
    } catch (err) {
      setError(err);
      setBusyKey(null);
    }
  }, []);

  return { start, busyKey, error };
}
