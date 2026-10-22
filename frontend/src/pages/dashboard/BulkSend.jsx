import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorNote, Loading, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { formatDateTime, ghs, number, pluralize } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { notifyWalletChanged } from "../../lib/walletEvents";

const MAX_FILE_BYTES = 2 * 1024 * 1024;
const POLL_MS = 2000;

const CATEGORIES = [
  { value: "thank_you", label: "Thank you" },
  { value: "welcome", label: "Welcome" },
  { value: "holiday", label: "Holiday" },
  { value: "birthday", label: "Birthday" },
  { value: "custom", label: "Custom" },
];

const SKIP_REASONS = {
  recipient_opted_out: "opted out",
  daily_cap_reached: "over your daily spend limit",
  insufficient_funds: "not enough balance",
  sender_not_approved: "sender ID not approved",
};

const newToken = () =>
  (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`).slice(0, 64);

/** Same estimate the server uses: 160 characters per part (153 once split), or 70/67 with non-Latin characters. */
function smsParts(text) {
  if (!text) return 0;
  const ascii = /^[\x00-\x7f]*$/.test(text);
  const [single, multi] = ascii ? [160, 153] : [70, 67];
  return text.length <= single ? 1 : Math.ceil(text.length / multi);
}

function skipSummary(reasons) {
  return Object.entries(reasons || {})
    .filter(([, n]) => n > 0)
    .map(([code, n]) => `${number(n)} ${SKIP_REASONS[code] ?? code.replaceAll("_", " ")}`)
    .join(", ");
}

const isRunning = (c) => c && (c.status === "queued" || c.status === "running");

function CampaignBadge({ status }) {
  const tone = { done: "ok", running: "warn", queued: "warn", failed: "bad" }[status] ?? "";
  const label = { done: "Done", running: "Sending", queued: "Queued", failed: "Not started" }[status] ?? status;
  return <span className={`badge${tone ? ` badge--${tone}` : ""}`}>{label}</span>;
}

function Progress({ campaign }) {
  const handled = campaign.accepted + campaign.skipped + campaign.failed;
  const skipped = skipSummary(campaign.skipped_reasons);
  const settled = campaign.delivered != null
    ? [`${number(campaign.delivered)} delivered`, campaign.sent ? `${number(campaign.sent)} sent` : null,
      campaign.in_queue ? `${number(campaign.in_queue)} waiting` : null,
      campaign.delivery_failed ? `${number(campaign.delivery_failed)} failed (refunded)` : null].filter(Boolean).join(", ")
    : "";

  if (campaign.status === "failed") {
    return (
      <div className="notice notice--error" role="alert">
        This bulk send couldn't be started, so nothing was sent and you weren't charged. Try again in a moment.
      </div>
    );
  }
  if (isRunning(campaign)) {
    return (
      <div className="bulk__progress" role="status">
        <p><strong>Sending…</strong> {number(handled)} of {number(campaign.total)} processed.</p>
        <progress max={campaign.total} value={handled} aria-label="Bulk send progress" />
        <p className="field__hint">You can leave this page. It keeps sending in the background.</p>
      </div>
    );
  }
  return (
    <div className="notice notice--ok" role="status">
      <strong>Done.</strong> {pluralize(campaign.accepted, "message")} sent
      {campaign.cost_pesewas ? <> for {ghs(campaign.cost_pesewas)}</> : null}.
      {settled && <> {settled}.</>}
      {skipped && <> Skipped: {skipped}.</>}
      {campaign.failed > 0 && <> {pluralize(campaign.failed, "message")} hit an error and weren't sent.</>}
    </div>
  );
}

function ReviewPanel({ review, sending, onSend, error }) {
  const s = review.summary;
  const invalid = review.invalid ?? [];
  const warnings = review.warnings ?? {};
  const canSend = s.to_send > 0 && s.enough_funds && !sending;

  return (
    <section className="bulk__review" aria-labelledby="review-title">
      <h3 id="review-title" className="panel__title panel__title--small">
        {s.to_send > 0 ? `${pluralize(s.to_send, "person", "people")} will get this message` : "Nobody to send to yet"}
      </h3>

      <dl className="bulk__facts">
        <div><dt>Numbers found</dt><dd>{number(s.found)}</dd></div>
        {s.duplicates > 0 && <div><dt>Duplicates removed</dt><dd>{number(s.duplicates)}</dd></div>}
        {s.opted_out > 0 && <div><dt>Skipped (opted out)</dt><dd>{number(s.opted_out)}</dd></div>}
        {s.invalid > 0 && <div><dt>Not valid</dt><dd>{number(s.invalid)}</dd></div>}
        <div><dt>Cost</dt><dd>{ghs(s.cost_pesewas)} <span className="bulk__sub">({pluralize(s.sms_parts, "SMS part")})</span></dd></div>
        <div><dt>Wallet balance</dt><dd>{ghs(s.balance_pesewas)}</dd></div>
      </dl>

      {invalid.length > 0 && (
        <details className="bulk__invalid">
          <summary>See the {s.invalid > invalid.length ? `first ${invalid.length} of ${s.invalid} numbers` : s.invalid === 1 ? "number" : `${s.invalid} numbers`} that {s.invalid === 1 ? "was" : "were"} left out</summary>
          <ul>
            {invalid.map((item, i) => (
              <li key={i}><span className="mono">{item.value || "(blank)"}</span> <span className="bulk__sub">{item.where}: {item.reason}</span></li>
            ))}
          </ul>
        </details>
      )}

      {(warnings.bad_birth_dates > 0 || warnings.bad_emails > 0) && (
        <p className="field__hint">
          {warnings.bad_birth_dates > 0 && `${pluralize(warnings.bad_birth_dates, "birth date")} couldn't be read and will be left blank. `}
          {warnings.bad_emails > 0 && `${pluralize(warnings.bad_emails, "email address", "email addresses")} looked wrong and will be left blank.`}
        </p>
      )}

      {s.to_send > 0 && !s.enough_funds && (
        <div className="notice notice--error" role="alert">
          You need {ghs(s.shortfall_pesewas)} more to send this. <Link to="/dashboard/plans">Buy SMS</Link>
        </div>
      )}
      {s.to_send > 0 && s.enough_funds && s.within_daily_cap < s.to_send && (
        <div className="notice notice--info" role="status">
          Your daily spend limit only leaves room for {number(s.within_daily_cap)} of these today. The rest will be skipped.
        </div>
      )}

      {review.sample && (
        <p className="bulk__sample">
          <span className="field__label">Sample, to <span className="mono">{review.sample.to}</span></span>
          <span className="bulk__bubble">{review.sample.body}</span>
        </p>
      )}

      {error && <div className="notice notice--error" role="alert">{error}</div>}

      <button type="button" className="btn btn--forest" onClick={onSend} disabled={!canSend}>
        {sending ? "Sending…" : s.to_send > 0 ? `Send to ${pluralize(s.to_send, "person", "people")} · ${ghs(s.cost_pesewas)}` : "Send"}
      </button>
    </section>
  );
}

export default function BulkSend() {
  const templates = useApi("/templates");
  const senders = useApi("/sender-ids");
  const recent = useApi("/bulk");

  const [numbers, setNumbers] = useState("");
  const [file, setFile] = useState(null);
  const [fileKey, setFileKey] = useState(0);          // remounts the file input to clear it
  const [fileError, setFileError] = useState(null);
  const [category, setCategory] = useState("thank_you");
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [sender, setSender] = useState("");
  const [save, setSave] = useState(true);

  const [review, setReview] = useState(null);
  const [reviewing, setReviewing] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [campaign, setCampaign] = useState(null);
  const token = useRef(null);

  const suggested = useMemo(
    () => templates.data?.results.find((t) => t.category === category)?.body ?? "",
    [templates.data, category],
  );
  useEffect(() => {
    setText(suggested);
    setDirty(false);
  }, [suggested]);

  const approved = (senders.data?.results ?? []).filter((s) => s.status === "approved");

  /** Any change to what's being sent invalidates the review, so you never send something you didn't review. */
  function changed(setter) {
    return (value) => {
      setter(value);
      setReview(null);
      setError(null);
      token.current = null;
    };
  }

  function pickFile(event) {
    const picked = event.target.files?.[0] ?? null;
    if (picked && picked.size > MAX_FILE_BYTES) {
      setFileError("That file is too large. Keep it under 2 MB.");
      setFile(null);
    } else {
      setFileError(null);
      setFile(picked);
    }
    setReview(null);
    setError(null);
    token.current = null;
  }

  function clearFile() {
    setFile(null);
    setFileError(null);
    setFileKey((k) => k + 1);
    setReview(null);
    token.current = null;
  }

  function buildForm(dryRun) {
    const form = new FormData();
    form.append("numbers", numbers);
    if (file) form.append("file", file);
    form.append("category", category);
    if (dirty) form.append("message", text.trim());
    if (sender) form.append("sender_id", sender);
    form.append("save_customers", save ? "true" : "false");
    form.append("dry_run", dryRun ? "true" : "false");
    if (!dryRun) form.append("client_token", token.current);
    return form;
  }

  const hasInput = numbers.trim() !== "" || file != null;
  const hasMessage = text.trim() !== "";

  async function runReview(event) {
    event.preventDefault();
    setReviewing(true);
    setError(null);
    setCampaign(null);
    try {
      setReview(await api.post("/bulk", buildForm(true)));
      token.current = newToken();
    } catch (err) {
      setReview(null);
      setError(err);
    } finally {
      setReviewing(false);
    }
  }

  async function send() {
    if (!token.current) token.current = newToken();
    setSending(true);
    setError(null);
    try {
      const created = await api.post("/bulk", buildForm(false));
      setCampaign(created);
      setReview(null);
      setNumbers("");
      clearFile();
      token.current = null;
      notifyWalletChanged();
      recent.reload();
    } catch (err) {
      setError(err);
    } finally {
      setSending(false);
    }
  }

  // Follow a running batch until it finishes.
  const runningId = isRunning(campaign) ? campaign.id : null;
  useEffect(() => {
    if (!runningId) return undefined;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const latest = await api.get(`/bulk/${runningId}`);
        if (cancelled) return;
        setCampaign(latest);
        if (!isRunning(latest)) {
          clearInterval(timer);
          notifyWalletChanged();
          recent.reload();
        }
      } catch {
        /* a missed poll is fine: try again on the next tick */
      }
    }, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [runningId, recent.reload]);

  const formError = error && error.code !== "validation_error" ? error.message : null;
  const fieldErrors = error?.fields ?? {};
  const rows = recent.data?.results ?? [];

  return (
    <>
      <PageHeader title="Bulk SMS">
        Send one message to many people at once. Paste their numbers or upload a contacts file, check the summary, then send.
      </PageHeader>

      <section className="panel" aria-labelledby="bulk-title">
        <h2 id="bulk-title" className="panel__title">New bulk message</h2>

        <form className="bulkform" onSubmit={runReview} noValidate>
          <fieldset className="bulk__who">
            <legend className="field__label">Who is it going to?</legend>
            <div className="bulk__split">
              <div className="field">
                <label className="field__label" htmlFor="bulk-numbers">Paste phone numbers</label>
                <textarea id="bulk-numbers" className="field__input compose__textarea" rows={6}
                  placeholder={"024 123 4567, 055 987 6543\n0201112222"}
                  value={numbers} onChange={(e) => changed(setNumbers)(e.target.value)} />
                <p className="field__hint">
                  Separate numbers with a comma, colon, pipe ( | ) or a new line. Any Ghana format works, like 024 123 4567 or +233241234567.
                </p>
              </div>

              <div className="field">
                <label className="field__label" htmlFor="bulk-file">Or upload a file</label>
                <input id="bulk-file" key={fileKey} type="file" className="field__input field__input--file"
                  accept=".csv,.txt,.xlsx" onChange={pickFile}
                  aria-invalid={fileError ? "true" : undefined} aria-describedby="bulk-file-hint" />
                {fileError
                  ? <p id="bulk-file-hint" className="field__error">{fileError}</p>
                  : (
                    <p id="bulk-file-hint" className="field__hint">
                      CSV, Excel (.xlsx) or text, up to 2,000 numbers. Columns like Phone Number, First Name, Last Name, Email
                      and Birth Date are picked up automatically. <a href="/api/bulk/sample" download>Download a sample file</a>.
                    </p>
                  )}
                {file && <button type="button" className="btn btn--link" onClick={clearFile}>Remove {file.name}</button>}
              </div>
            </div>
            {fieldErrors.numbers && <p className="field__error">{fieldErrors.numbers}</p>}
          </fieldset>

          <div className="compose__row">
            <div className="field">
              <label className="field__label" htmlFor="bulk-category">Message type</label>
              <select id="bulk-category" className="field__input" value={category}
                onChange={(e) => changed(setCategory)(e.target.value)}>
                {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="bulk-sender">Send as</label>
              <select id="bulk-sender" className="field__input" value={sender}
                onChange={(e) => changed(setSender)(e.target.value)}>
                <option value="">Default sender</option>
                {approved.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
              </select>
            </div>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="bulk-text">Message</label>
            <textarea id="bulk-text" className="field__input compose__textarea" rows={4} maxLength={480}
              value={text}
              onChange={(e) => { setText(e.target.value); setDirty(true); setReview(null); setError(null); token.current = null; }}
              aria-describedby="bulk-text-hint" />
            <p id="bulk-text-hint" className="field__hint">
              {text.length} characters, about {pluralize(smsParts(text), "SMS part")} each.
              Use <code>{"{first_name}"}</code>, <code>{"{customer_name}"}</code> and <code>{"{business_name}"}</code> to
              personalise it; people with no name on file get “there”.{" "}
              {dirty ? "Edited, so your saved template stays as it is." : "From your template."}{" "}
              <Link to="/dashboard/templates">Edit templates</Link>
            </p>
            {fieldErrors.message && <p className="field__error">{fieldErrors.message}</p>}
          </div>

          <label className="bulk__check">
            <input type="checkbox" checked={save} onChange={(e) => changed(setSave)(e.target.checked)} />
            <span>
              <strong>Save these people to my customers</strong>
              <span className="field__hint">
                Keeps their names, emails and birth dates. If your list includes birth dates and automatic birthday messages are on, they'll get a birthday message too.
              </span>
            </span>
          </label>

          <div className="senderform__actions">
            <button type="submit" className="btn btn--outline" disabled={reviewing || sending || !hasInput || !hasMessage}>
              {reviewing ? "Checking…" : "Review before sending"}
            </button>
            {!hasInput && <span className="field__hint">Paste some numbers or choose a file first.</span>}
          </div>
        </form>

        {formError && !review && <div className="notice notice--error" role="alert">{formError}</div>}
        {review && <ReviewPanel review={review} sending={sending} onSend={send} error={formError} />}
        {campaign && <Progress campaign={campaign} />}
      </section>

      <section className="panel" aria-labelledby="recent-title">
        <h2 id="recent-title" className="panel__title">Recent bulk sends</h2>
        {recent.error && <ErrorNote error={recent.error} onRetry={recent.reload} />}
        {!recent.data && recent.loading && <Loading />}
        {recent.data && rows.length === 0 && (
          <EmptyState title="No bulk sends yet">When you send to a list, it shows up here with how many were delivered.</EmptyState>
        )}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">When</th><th scope="col">Message</th><th scope="col">People</th>
                  <th scope="col">Sent</th><th scope="col">Delivered</th><th scope="col">Skipped</th>
                  <th scope="col">Failed</th><th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id}>
                    <td>{formatDateTime(c.created_at)}</td>
                    <td className="bulk__body" title={c.body}>{c.body}</td>
                    <td>{number(c.total)}</td>
                    <td>{number(c.accepted)}</td>
                    <td>{c.delivered == null ? "—" : number(c.delivered)}</td>
                    <td title={skipSummary(c.skipped_reasons)}>{number(c.skipped)}</td>
                    <td>{number((c.failed || 0) + (c.delivery_failed || 0))}</td>
                    <td><CampaignBadge status={c.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
