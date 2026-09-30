import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

/** GET `path` and keep { data, error, loading }. Refetches when `path` changes or reload() is called.
 *  Pass null to skip. Previous data stays visible while a new page loads. */
export function useApi(path) {
  const [state, setState] = useState({ data: null, error: null, loading: path != null });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (path == null) return undefined;
    const controller = new AbortController();
    setState((s) => ({ ...s, error: null, loading: true }));
    api.get(path, { signal: controller.signal }).then(
      (data) => setState({ data, error: null, loading: false }),
      (error) => {
        if (error?.name !== "AbortError") setState({ data: null, error, loading: false });
      },
    );
    return () => controller.abort();
  }, [path, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}
