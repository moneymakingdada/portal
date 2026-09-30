import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, onUnauthorized } from "./api";

const AuthContext = createContext(null);

/** status: "loading" (asking the server who we are) | "authed" | "anon" */
export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: "loading", user: null });

  useEffect(() => {
    let alive = true;
    api.get("/auth/me").then(
      (data) => alive && setState(data?.user ? { status: "authed", user: data.user } : { status: "anon", user: null }),
      () => alive && setState({ status: "anon", user: null }),
    );
    return () => {
      alive = false;
    };
  }, []);

  // A 403 "not signed in" anywhere (expired session) sends the user back to log in.
  useEffect(() => onUnauthorized(() => setState({ status: "anon", user: null })), []);

  const signIn = useCallback((user) => setState({ status: "authed", user }), []);
  const signOut = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setState({ status: "anon", user: null });
    }
  }, []);

  const value = useMemo(() => ({ ...state, signIn, signOut }), [state, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
