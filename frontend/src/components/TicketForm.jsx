import { useState } from "react";
import { api, fieldError } from "../lib/api";
import { TextField } from "./ui";
import "../styles/support.css";

const MAX_SUBJECT = 140;
const MAX_DETAILS = 2000;

/** Send a problem to our staff. Used on the Support page and inside the chat. */
export default function TicketForm({ onCreated, initialSubject = "", submitLabel = "Send to our team" }) {
  const [subject, setSubject] = useState(initialSubject);
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const ticket = await api.post("/support/tickets", { subject: subject.trim(), details: details.trim() });
      setSubject("");
      setDetails("");
      onCreated?.(ticket);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const ready = subject.trim() && details.trim();
  return (
    <form className="ticketform" onSubmit={submit} noValidate>
      <TextField label="What's the problem?" value={subject} maxLength={MAX_SUBJECT} required
        onChange={(e) => setSubject(e.target.value)} error={fieldError(error, "subject")} />
      <div className="field">
        <label className="field__label" htmlFor="ticket-details">Details</label>
        <textarea id="ticket-details" className="field__input compose__textarea" rows={4} maxLength={MAX_DETAILS} required
          placeholder="What happened, what you expected, and any message ID or payment reference."
          value={details} onChange={(e) => setDetails(e.target.value)} />
      </div>
      {error && <div className="notice notice--error" role="alert">{error.message}</div>}
      <button type="submit" className="btn btn--primary" disabled={busy || !ready}>
        {busy ? "Sending…" : submitLabel}
      </button>
    </form>
  );
}
