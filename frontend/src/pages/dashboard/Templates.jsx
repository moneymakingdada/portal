import { useState } from "react";
import { EmptyState, ErrorNote, Loading, PageHeader, TextField } from "../../components/ui";
import { api, fieldError } from "../../lib/api";
import { useApi } from "../../lib/useApi";

const CATEGORY_LABELS = {
  thank_you: "Thank you", birthday: "Birthday", holiday: "Holiday", welcome: "Welcome", custom: "Custom",
};
const CATEGORY_HINTS = {
  thank_you: "Sent after a purchase, or any time you want to say thanks.",
  birthday: "Sent automatically on a customer's birthday, if you turn that on from Customers.",
  holiday: "For Christmas, Eid, New Year, or any seasonal greeting you send out.",
  welcome: "Sent to a new customer the first time you do business with them.",
  custom: "The starting text for one-off messages that don't fit another category.",
};
const ORDER = ["thank_you", "birthday", "holiday", "welcome", "custom"];

function TemplateCard({ entry, onSaved, onReset }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(entry.name);
  const [body, setBody] = useState(entry.body);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const saved = entry.is_suggested
        ? await api.post("/templates", { category: entry.category, name, body, is_default: true })
        : await api.patch(`/templates/${entry.id}`, { name, body });
      setEditing(false);
      onSaved(saved);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    setName(entry.name);
    setBody(entry.body);
    setEditing(false);
    setError(null);
  }

  return (
    <article className="tplcard">
      <div className="tplcard__head">
        <div>
          <h3 className="tplcard__title">{CATEGORY_LABELS[entry.category]}</h3>
          <p className="tplcard__hint">{CATEGORY_HINTS[entry.category]}</p>
        </div>
        <span className={`badge badge--plain${entry.is_suggested ? "" : " badge--ok"}`}>
          {entry.is_suggested ? "Suggested" : "Your template"}
        </span>
      </div>

      {editing ? (
        <form className="tplcard__form" onSubmit={save} noValidate>
          <TextField label="Internal name" name="name" value={name} onChange={(e) => setName(e.target.value)}
            error={fieldError(error, "name")} />
          <div className="field">
            <label className="field__label" htmlFor={`body-${entry.category}`}>Message</label>
            <textarea id={`body-${entry.category}`} className="field__input tplcard__textarea" rows={3}
              maxLength={480} value={body} onChange={(e) => setBody(e.target.value)} />
            <p className="field__hint">Use {"{customer_name}"}, {"{business_name}"} and {"{amount}"} — they're filled in when a message sends.</p>
            {fieldError(error, "body") && <p className="field__error">{fieldError(error, "body")}</p>}
          </div>
          <div className="tplcard__actions">
            <button type="submit" className="btn btn--forest btn--small" disabled={busy || !body.trim()}>
              {busy ? "Saving…" : "Save"}
            </button>
            <button type="button" className="btn btn--outline btn--small" onClick={cancel} disabled={busy}>Cancel</button>
          </div>
          {error && error.code !== "validation_error" && <div className="notice notice--error" role="alert">{error.message}</div>}
        </form>
      ) : (
        <>
          <p className="tplcard__body">{entry.body}</p>
          <div className="tplcard__actions">
            <button type="button" className="btn btn--outline btn--small" onClick={() => setEditing(true)}>
              {entry.is_suggested ? "Customize" : "Edit"}
            </button>
            {!entry.is_suggested && (
              <button type="button" className="btn btn--link" onClick={() => onReset(entry)}>Reset to suggested</button>
            )}
          </div>
        </>
      )}
    </article>
  );
}

export default function Templates() {
  const { data, error, loading, reload } = useApi("/templates");

  async function handleReset(entry) {
    if (!window.confirm("Reset this to the suggested text? Your version will be deleted.")) return;
    await api.delete(`/templates/${entry.id}`);
    reload();
  }

  const entries = data
    ? [...data.results].sort((a, b) => ORDER.indexOf(a.category) - ORDER.indexOf(b.category))
    : [];

  return (
    <>
      <PageHeader title="Templates">
        The starting text for each kind of customer message. Every category ships with a suggestion you can
        send as-is, or customize to sound like you.
      </PageHeader>

      {error && <ErrorNote error={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && entries.length === 0 && <EmptyState title="Nothing here yet" />}
      {entries.length > 0 && (
        <div className="tplgrid">
          {entries.map((entry) => (
            <TemplateCard key={entry.category} entry={entry} onSaved={reload} onReset={handleReset} />
          ))}
        </div>
      )}
    </>
  );
}
