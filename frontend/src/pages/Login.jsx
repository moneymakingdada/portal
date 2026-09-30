import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, fieldError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { TextField } from "../components/ui";
import AuthLayout from "./AuthLayout";

export default function Login() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || "/dashboard";

  const [form, setForm] = useState({ email: "", password: "" });
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (name) => (event) => setForm((f) => ({ ...f, [name]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await api.post("/auth/login", form);
      signIn(data.user);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  const formError = error && error.code !== "validation_error" ? error.message : null;

  return (
    <AuthLayout
      title="Log in"
      subtitle="Welcome back. Pick up where you left off."
      footer={<>New here? <Link to="/signup">Create an account</Link></>}
    >
      <form className="auth__form" onSubmit={submit} noValidate>
        {formError && <div className="notice notice--error" role="alert">{formError}</div>}
        <TextField
          label="Email" type="email" name="email" autoComplete="email" autoFocus required
          value={form.email} onChange={set("email")} error={fieldError(error, "email")}
        />
        <TextField
          label="Password" name="password" autoComplete="current-password" required
          type={showPassword ? "text" : "password"}
          value={form.password} onChange={set("password")} error={fieldError(error, "password")}
          trailing={
            <button type="button" className="field__toggle" onClick={() => setShowPassword((s) => !s)} aria-pressed={showPassword}>
              {showPassword ? "Hide" : "Show"}
            </button>
          }
        />
        <button type="submit" className="btn btn--forest btn--block" disabled={busy}>
          {busy ? <><span className="spinner" aria-hidden="true" /> Logging in…</> : "Log in"}
        </button>
      </form>
    </AuthLayout>
  );
}
