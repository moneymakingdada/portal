import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fieldError } from "../lib/api";
import { useAuth } from "../lib/auth";
import OtpInput from "../components/OtpInput";
import { TextField } from "../components/ui";
import AuthLayout from "./AuthLayout";

const STORAGE_KEY = "signup-pending";
const EMPTY_FORM = { full_name: "", organization_name: "", email: "", phone: "", password: "" };

/** Only non-secret state is kept (never the password), so a refresh resumes at the code screen. */
function loadPending() {
  try {
    const pending = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
    if (pending?.signup_id && pending.expires_at > Date.now()) return pending;
  } catch {
    /* ignore corrupt storage */
  }
  sessionStorage.removeItem(STORAGE_KEY);
  return null;
}

function savePending(pending) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(pending));
  } catch {
    /* storage unavailable: resuming after refresh just won't work */
  }
}

function useCountdown(targetMs) {
  const [left, setLeft] = useState(() => Math.max(0, Math.ceil((targetMs - Date.now()) / 1000)));
  useEffect(() => {
    const tick = () => setLeft(Math.max(0, Math.ceil((targetMs - Date.now()) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [targetMs]);
  return left;
}

const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export default function Signup() {
  const [pending, setPending] = useState(loadPending);
  const [form, setForm] = useState(EMPTY_FORM);   // kept in memory so "use a different number" doesn't wipe it
  const [notice, setNotice] = useState(null);

  const update = (next) => {
    savePending(next);
    setPending(next);
  };
  const restart = (message) => {
    sessionStorage.removeItem(STORAGE_KEY);
    setPending(null);
    setNotice(message || null);
  };

  return (
    <AuthLayout
      title={pending ? "Check your phone" : "Create your account"}
      subtitle={pending ? null : "Start with a free test key. We'll text a code to confirm your number."}
      footer={<>Already have an account? <Link to="/login">Log in</Link></>}
    >
      {pending ? (
        <VerifyStep pending={pending} onUpdate={update} onRestart={restart} />
      ) : (
        <DetailsStep form={form} setForm={setForm} notice={notice} onSent={update} />
      )}
    </AuthLayout>
  );
}

function DetailsStep({ form, setForm, notice, onSent }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [showPassword, setShowPassword] = useState(false);
  const set = (name) => (event) => setForm((f) => ({ ...f, [name]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post("/auth/signup", form);
      const now = Date.now();
      onSent({
        signup_id: r.signup_id,
        phone_masked: r.phone_masked,
        code_length: r.code_length,
        expires_at: now + r.expires_in * 1000,
        resend_at: now + r.resend_in * 1000,
      });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  const formError = error && error.code !== "validation_error" ? error.message : null;

  return (
    <form className="auth__form" onSubmit={submit} noValidate>
      {notice && <div className="notice notice--info" role="status">{notice}</div>}
      {formError && <div className="notice notice--error" role="alert">{formError}</div>}
      <TextField label="Your name" name="full_name" autoComplete="name" required autoFocus
        value={form.full_name} onChange={set("full_name")} error={fieldError(error, "full_name")} />
      <TextField label="Business or app name" name="organization_name" autoComplete="organization" required
        value={form.organization_name} onChange={set("organization_name")} error={fieldError(error, "organization_name")} />
      <TextField label="Email" type="email" name="email" autoComplete="email" required
        value={form.email} onChange={set("email")} error={fieldError(error, "email")} />
      <TextField label="Mobile number" type="tel" name="phone" autoComplete="tel" inputMode="tel" required
        prefix="+233" placeholder="24 123 4567"
        hint="We'll text a 6-digit code to this number."
        value={form.phone} onChange={set("phone")} error={fieldError(error, "phone")} />
      <TextField label="Password" name="password" autoComplete="new-password" required
        type={showPassword ? "text" : "password"}
        hint="At least 10 characters. Avoid common passwords."
        value={form.password} onChange={set("password")} error={fieldError(error, "password")}
        trailing={
          <button type="button" className="field__toggle" onClick={() => setShowPassword((s) => !s)} aria-pressed={showPassword}>
            {showPassword ? "Hide" : "Show"}
          </button>
        } />
      <button type="submit" className="btn btn--forest btn--block" disabled={busy}>
        {busy ? <><span className="spinner" aria-hidden="true" /> Sending code…</> : "Send verification code"}
      </button>
    </form>
  );
}

function VerifyStep({ pending, onUpdate, onRestart }) {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const length = pending.code_length || 6;

  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [info, setInfo] = useState(null);
  const [inputKey, setInputKey] = useState(0);    // remounting the boxes re-focuses the first one
  const resendIn = useCountdown(pending.resend_at);
  const expiresIn = useCountdown(pending.expires_at);

  async function verify(value) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const data = await api.post("/auth/signup/verify", { signup_id: pending.signup_id, code: value });
      sessionStorage.removeItem(STORAGE_KEY);
      signIn(data.user);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      if (err.code === "signup_expired") {
        onRestart("Your sign-up session expired. Fill in your details again.");
        return;
      }
      if (err.code === "wrong_code") {
        const left = err.extra.attempts_left;
        setError({ message: left > 0 ? `That code is incorrect. ${left} ${left === 1 ? "attempt" : "attempts"} left.` : "That code is incorrect. Request a new one." });
      } else {
        setError(err);
      }
      setCode("");
      setInputKey((k) => k + 1);
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    setInfo(null);
    try {
      const r = await api.post("/auth/signup/resend", { signup_id: pending.signup_id });
      const now = Date.now();
      onUpdate({ ...pending, expires_at: now + r.expires_in * 1000, resend_at: now + r.resend_in * 1000 });
      setCode("");
      setInputKey((k) => k + 1);
      setInfo(`We sent a new code to ${pending.phone_masked}.`);
    } catch (err) {
      if (err.code === "signup_expired" || err.code === "too_many_resends") {
        onRestart(err.code === "signup_expired" ? "Your sign-up session expired. Fill in your details again." : err.message);
        return;
      }
      if (err.code === "cooldown" && err.retryAfter) onUpdate({ ...pending, resend_at: Date.now() + err.retryAfter * 1000 });
      setError(err);
    }
  }

  return (
    <div className="auth__form">
      <p className="auth__subtitle auth__subtitle--flush">
        We sent a {length}-digit code to <strong className="mono">{pending.phone_masked}</strong>.
      </p>
      {info && <div className="notice notice--ok" role="status">{info}</div>}
      {error && <div className="notice notice--error" role="alert">{error.message}</div>}
      {!error && expiresIn === 0 && (
        <div className="notice notice--info" role="status">This code has expired. Send a new one.</div>
      )}

      <OtpInput key={inputKey} length={length} value={code} onChange={setCode} onComplete={verify}
        disabled={busy} invalid={Boolean(error)} autoFocus />

      <button type="button" className="btn btn--forest btn--block" disabled={busy || code.length < length} onClick={() => verify(code)}>
        {busy ? <><span className="spinner" aria-hidden="true" /> Verifying…</> : "Verify and create account"}
      </button>

      <div className="auth__row">
        {resendIn > 0 ? (
          <span className="auth__muted">Send a new code in {clock(resendIn)}</span>
        ) : (
          <button type="button" className="btn btn--link" onClick={resend} disabled={busy}>Send a new code</button>
        )}
        <button type="button" className="btn btn--link" onClick={() => onRestart()} disabled={busy}>Use a different number</button>
      </div>
    </div>
  );
}
