import { useId, useRef, useState } from "react";
import { EmptyState, ErrorNote, Loading, PageHeader, TextField } from "../../components/ui";
import { APP_NAME } from "../../config";
import { api, fieldError } from "../../lib/api";
import { formatDate } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const MAX_BYTES = 5 * 1024 * 1024;

const STATUS = {
  pending: { label: "Pending review", tone: "warn" },
  approved: { label: "Approved", tone: "ok" },
  rejected: { label: "Rejected", tone: "bad" },
};

function FileField({ label, hint, accept, error, onPick }) {
  const id = useId();
  const describedBy = `${id}-note`;
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>{label}</label>
      <input id={id} type="file" className="field__input field__input--file" accept={accept}
        aria-invalid={error ? "true" : undefined} aria-describedby={describedBy}
        onChange={(event) => onPick(event.target.files?.[0] ?? null)} />
      {error ? <p id={describedBy} className="field__error">{error}</p> : <p id={describedBy} className="field__hint">{hint}</p>}
    </div>
  );
}

export default function SenderIds() {
  const { data, error, loading, reload } = useApi("/sender-ids");
  const formRef = useRef(null);
  const [formKey, setFormKey] = useState(0);        // remounts the file inputs to clear them after a submit
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [business, setBusiness] = useState(false);
  const [letter, setLetter] = useState(null);
  const [supporting, setSupporting] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [localErrors, setLocalErrors] = useState({});
  const [sent, setSent] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [actionError, setActionError] = useState(null);

  const senders = data?.results ?? [];
  const supportingLabel = business ? "Business registration certificate" : "Ghana Card (front)";
  const templateUrl = `/api/sender-ids/letter-template?type=${business ? "business" : "individual"}`
    + (name.trim() ? `&sender_id=${encodeURIComponent(name.trim())}` : "");

  function pick(setter, key) {
    return (file) => {
      setter(file);
      setLocalErrors((e) => ({ ...e, [key]: file && file.size > MAX_BYTES ? "That file is too large. The limit is 5 MB." : null }));
    };
  }

  function clearProblem(key) {
    setLocalErrors((e) => (e[key] ? { ...e, [key]: null } : e));
  }

  async function submit(event) {
    event.preventDefault();
    const problems = {};
    if (!name.trim()) problems.name = "Enter the name you want to send as.";
    if (purpose.trim().length < 10) problems.purpose = "Describe what you'll send (at least 10 characters).";
    if (!letter) problems.letter = "Upload your signed letter of authorization.";
    if (!supporting) problems.supporting = `Upload your ${supportingLabel.toLowerCase()}.`;
    if (Object.values({ ...localErrors, ...problems }).some(Boolean)) {
      setLocalErrors({ ...localErrors, ...problems });
      return;
    }
    const form = new FormData();
    form.append("name", name.trim());
    form.append("purpose", purpose.trim());
    form.append("is_business", business ? "true" : "false");
    form.append("letter", letter);
    form.append("supporting", supporting);

    setSubmitting(true);
    setSubmitError(null);
    setSent(null);
    try {
      const created = await api.post("/sender-ids", form);
      setSent(created.name);
      setName("");
      setPurpose("");
      setBusiness(false);
      setLetter(null);
      setSupporting(null);
      setLocalErrors({});
      setFormKey((k) => k + 1);
      reload();
    } catch (err) {
      setSubmitError(err);
    } finally {
      setSubmitting(false);
    }
  }

  async function withdraw(id) {
    setActionError(null);
    try {
      await api.delete(`/sender-ids/${id}`);
      setConfirming(null);
      reload();
    } catch (err) {
      setActionError(err);
    }
  }

  function resubmit(sender) {
    setName(sender.name);
    setPurpose(sender.purpose);
    setBusiness(sender.is_business);
    setSent(null);
    setSubmitError(null);
    formRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }

  const formError = submitError && submitError.code !== "validation_error" ? submitError.message : null;

  return (
    <>
      <PageHeader title="Sender IDs">
        A sender ID is the name your customers see instead of a phone number. Until yours is approved, messages go out as
        “{APP_NAME}”. The networks need a signed letter of authorization, so you upload it here and we review it.
      </PageHeader>

      <section className="panel" aria-labelledby="request-title" ref={formRef}>
        <h2 id="request-title" className="panel__title">Request a sender ID</h2>
        {sent && (
          <div className="notice notice--ok" role="status">
            Request for “{sent}” sent. We'll review your documents, then ask the networks to whitelist the name, which can
            take up to 72 hours.
          </div>
        )}
        <form className="senderform" onSubmit={submit} noValidate>
          <TextField label="Sender ID" name="sender_name" placeholder="e.g. ACME" maxLength={11} required
            hint="3 to 11 letters or numbers. This is what recipients see."
            value={name} onChange={(e) => { setName(e.target.value); clearProblem("name"); }}
            error={localErrors.name || fieldError(submitError, "name")} />

          <div className="field">
            <label className="field__label" htmlFor="sender-purpose">What will you send?</label>
            <textarea id="sender-purpose" className="field__input compose__textarea" rows={3} maxLength={300} required
              aria-invalid={localErrors.purpose || fieldError(submitError, "purpose") ? "true" : undefined}
              placeholder="e.g. Order confirmations and receipts for customers of Adom Bakery."
              value={purpose} onChange={(e) => { setPurpose(e.target.value); clearProblem("purpose"); }} />
            {localErrors.purpose || fieldError(submitError, "purpose")
              ? <p className="field__error">{localErrors.purpose || fieldError(submitError, "purpose")}</p>
              : <p className="field__hint">Write at least 10 characters.</p>}
          </div>

          <fieldset className="mode">
            <legend className="field__label">This name is for</legend>
            <label className={`mode__option${!business ? " is-selected" : ""}`}>
              <input type="radio" name="sender_kind" checked={!business} onChange={() => setBusiness(false)} />
              <span><strong>An individual</strong> You'll upload your Ghana Card.</span>
            </label>
            <label className={`mode__option${business ? " is-selected" : ""}`}>
              <input type="radio" name="sender_kind" checked={business} onChange={() => setBusiness(true)} />
              <span><strong>A business</strong> You'll upload its registration certificate.</span>
            </label>
          </fieldset>

          <p className="field__hint">
            Don't have a letter yet?{" "}
            <a href={templateUrl}>Download the sample letter</a>. It's pre-filled with your details. Fill in the
            highlighted blanks, sign it, then save or scan it as a PDF or Word file.
          </p>

          <div className="senderform__files" key={formKey}>
            <FileField label="Signed letter of authorization" accept=".pdf,.doc,.docx"
              hint="PDF or Word, up to 5 MB." onPick={pick(setLetter, "letter")}
              error={localErrors.letter || fieldError(submitError, "letter")} />
            <FileField label={supportingLabel} accept=".pdf,.jpg,.jpeg,.png"
              hint="PDF, JPG or PNG, up to 5 MB." onPick={pick(setSupporting, "supporting")}
              error={localErrors.supporting || fieldError(submitError, "supporting")} />
          </div>

          <div className="senderform__actions">
            <button type="submit" className="btn btn--forest" disabled={submitting}>
              {submitting ? "Sending…" : "Submit for review"}
            </button>
          </div>
        </form>
        {formError && <div className="notice notice--error" role="alert">{formError}</div>}
      </section>

      <section className="panel" aria-labelledby="senders-title">
        <h2 id="senders-title" className="panel__title">Your requests</h2>
        {error && <ErrorNote error={error} onRetry={reload} />}
        {actionError && <div className="notice notice--error" role="alert">{actionError.message}</div>}
        {!data && loading && <Loading />}
        {data && senders.length === 0 && (
          <EmptyState title="No sender IDs yet">Submit a request above to send under your own name.</EmptyState>
        )}
        {senders.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th><th scope="col">Type</th><th scope="col">Status</th>
                  <th scope="col">Submitted</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {senders.map((s) => {
                  const { label, tone } = STATUS[s.status] ?? { label: s.status, tone: "" };
                  return (
                    <tr key={s.id}>
                      <th scope="row" className="table__name sender__cell">
                        {s.name}
                        <span className="sender__purpose">{s.purpose}</span>
                      </th>
                      <td>{s.is_business ? "Business" : "Individual"}</td>
                      <td>
                        <span className={`badge${tone ? ` badge--${tone}` : ""}`}>{label}</span>
                        {s.status === "rejected" && s.rejection_reason && <p className="sender__reason">{s.rejection_reason}</p>}
                      </td>
                      <td>{formatDate(s.submitted_at)}</td>
                      <td className="table__actions">
                        {s.status === "rejected" && (
                          <button type="button" className="btn btn--outline btn--small" onClick={() => resubmit(s)}>
                            Fix and resubmit <span className="sr-only">{s.name}</span>
                          </button>
                        )}{" "}
                        {s.status !== "approved" && (confirming === s.id ? (
                          <span className="confirm">
                            <span>Withdraw this request?</span>
                            <button type="button" className="btn btn--danger btn--small" onClick={() => withdraw(s.id)}>Withdraw</button>
                            <button type="button" className="btn btn--outline btn--small" onClick={() => setConfirming(null)}>Keep</button>
                          </span>
                        ) : (
                          <button type="button" className="btn btn--outline btn--small" onClick={() => setConfirming(s.id)}>
                            Withdraw <span className="sr-only">{s.name}</span>
                          </button>
                        ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {senders.some((s) => s.status === "approved") && (
          <p className="field__hint">Approved? Pass it as <code className="mono">sender_id</code> when you send, or leave it out to use “{APP_NAME}”.</p>
        )}
      </section>
    </>
  );
}
