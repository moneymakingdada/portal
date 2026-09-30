import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { IconArrowLeft } from "../../components/icons";
import { EmptyState, ErrorNote, Loading, StatusBadge, TextField } from "../../components/ui";
import { api, fieldError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDate, formatDateTime, ghs } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { notifyWalletChanged } from "../../lib/walletEvents";

const CATEGORY_LABELS = {
  thank_you: "Thank you", birthday: "Birthday", holiday: "Holiday", welcome: "Welcome", custom: "Custom",
};
const SENDABLE_CATEGORIES = ["thank_you", "birthday", "holiday", "welcome"];

function renderPreview(body, { customerName, businessName }) {
  return body
    .replaceAll("{customer_name}", customerName || "there")
    .replaceAll("{business_name}", businessName || "");
}

function EditCustomerForm({ customer, onSaved, onCancel }) {
  const [form, setForm] = useState({
    name: customer.name, phone: customer.phone, email: customer.email,
    birthday: customer.birthday || "", notes: customer.notes,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (name) => (e) => setForm((f) => ({ ...f, [name]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const updated = await api.patch(`/customers/${customer.id}`, { ...form, birthday: form.birthday || null });
      onSaved(updated);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="customerform" onSubmit={submit} noValidate>
      <TextField label="Name" name="name" value={form.name} onChange={set("name")} error={fieldError(error, "name")} />
      <TextField label="Phone" name="phone" type="tel" value={form.phone} onChange={set("phone")} error={fieldError(error, "phone")} />
      <TextField label="Email" name="email" type="email" value={form.email} onChange={set("email")} error={fieldError(error, "email")} />
      <TextField label="Birthday" name="birthday" type="date" value={form.birthday} onChange={set("birthday")} error={fieldError(error, "birthday")} />
      <TextField label="Notes" name="notes" value={form.notes} onChange={set("notes")} error={fieldError(error, "notes")} />
      <div className="customerform__actions">
        <button type="submit" className="btn btn--forest btn--small" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" className="btn btn--outline btn--small" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
      {error && error.code !== "validation_error" && <div className="notice notice--error" role="alert">{error.message}</div>}
    </form>
  );
}

function Compose({ customerId, customerName, onSent }) {
  const { user } = useAuth();
  const businessName = user.organization?.name || "";
  const templates = useApi("/templates");
  const [category, setCategory] = useState("thank_you");
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [sent, setSent] = useState(null);

  const suggested = useMemo(() => {
    const entry = templates.data?.results.find((t) => t.category === category);
    return entry ? renderPreview(entry.body, { customerName, businessName }) : "";
  }, [templates.data, category, customerName, businessName]);

  useEffect(() => {
    setText(suggested);
    setDirty(false);
  }, [suggested]);

  async function send(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSent(null);
    try {
      const payload = dirty ? { message: text } : { category };
      if (amount) payload.amount = Number(amount);
      const result = await api.post(`/customers/${customerId}/messages`, payload);
      setSent(result.body);
      setAmount("");
      onSent();
      notifyWalletChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="compose" onSubmit={send} noValidate>
      <div className="compose__row">
        <div className="field">
          <label className="field__label" htmlFor="compose-category">Message type</label>
          <select id="compose-category" className="field__input" value={category}
            onChange={(e) => setCategory(e.target.value)}>
            {SENDABLE_CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
          </select>
        </div>
        <TextField label="Amount, GHS (optional)" name="amount" type="number" min="0" step="0.01"
          placeholder="45.00" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </div>

      <div className="field">
        <label className="field__label" htmlFor="compose-text">Message</label>
        <textarea id="compose-text" className="field__input compose__textarea" rows={3} maxLength={480}
          value={text} onChange={(e) => { setText(e.target.value); setDirty(true); }} />
        <p className="field__hint">
          {dirty ? "Edited — this won't change your saved template." : "From your " + CATEGORY_LABELS[category].toLowerCase() + " template."}
          {" "}<Link to="/dashboard/templates">Edit templates</Link>
        </p>
      </div>

      <button type="submit" className="btn btn--forest" disabled={busy || !text.trim()}>
        {busy ? "Sending…" : "Send message"}
      </button>
      {error && <div className="notice notice--error" role="alert">{error.message}</div>}
      {sent && <div className="notice notice--ok" role="status">Sent: “{sent}”</div>}
    </form>
  );
}

export default function CustomerDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const customerApi = useApi(`/customers/${id}`);
  const historyApi = useApi(`/customers/${id}/messages`);
  const [editing, setEditing] = useState(false);

  async function remove() {
    if (!window.confirm("Remove this customer? Their message history stays in your log.")) return;
    await api.delete(`/customers/${id}`);
    navigate("/dashboard/customers");
  }

  if (customerApi.error) {
    return (
      <>
        <Link to="/dashboard/customers" className="backlink"><IconArrowLeft width={16} height={16} /> Customers</Link>
        <ErrorNote error={customerApi.error} onRetry={customerApi.reload} />
      </>
    );
  }
  if (!customerApi.data) return <Loading />;
  const customer = customerApi.data;

  return (
    <>
      <Link to="/dashboard/customers" className="backlink"><IconArrowLeft width={16} height={16} /> Customers</Link>

      <header className="pagehead">
        <h1 className="pagehead__title">{customer.name || customer.phone}</h1>
        <p className="pagehead__lede mono">{customer.phone}</p>
      </header>

      <section className="panel" aria-labelledby="details-title">
        <div className="panel__head">
          <h2 id="details-title" className="panel__title">Details</h2>
          {!editing && (
            <div className="panel__head-actions">
              <button type="button" className="btn btn--outline btn--small" onClick={() => setEditing(true)}>Edit</button>
              <button type="button" className="btn btn--danger btn--small" onClick={remove}>Remove</button>
            </div>
          )}
        </div>
        {editing ? (
          <EditCustomerForm customer={customer} onCancel={() => setEditing(false)}
            onSaved={() => { setEditing(false); customerApi.reload(); }} />
        ) : (
          <dl className="detail-grid">
            <div><dt>Email</dt><dd>{customer.email || "—"}</dd></div>
            <div><dt>Birthday</dt><dd>{customer.birthday ? formatDate(customer.birthday) : "—"}</dd></div>
            <div><dt>Customer since</dt><dd>{formatDate(customer.created_at)}</dd></div>
            <div><dt>Notes</dt><dd>{customer.notes || "—"}</dd></div>
          </dl>
        )}
      </section>

      <section className="panel" aria-labelledby="compose-title">
        <h2 id="compose-title" className="panel__title">Send a message</h2>
        <Compose customerId={id} customerName={customer.name} onSent={historyApi.reload} />
      </section>

      <section className="panel" aria-labelledby="history-title">
        <h2 id="history-title" className="panel__title">Message history</h2>
        {historyApi.error && <ErrorNote error={historyApi.error} onRetry={historyApi.reload} />}
        {!historyApi.data && historyApi.loading && <Loading />}
        {historyApi.data && historyApi.data.results.length === 0 && (
          <EmptyState title="No messages yet">Messages you send this customer will show up here.</EmptyState>
        )}
        {historyApi.data && historyApi.data.results.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th scope="col">Time</th><th scope="col">Type</th><th scope="col">Status</th><th scope="col" className="num">Cost</th></tr></thead>
              <tbody>
                {historyApi.data.results.map((m) => (
                  <tr key={m.id}>
                    <td>{formatDateTime(m.created_at)}</td>
                    <td>{CATEGORY_LABELS[m.category] || m.category || "—"}</td>
                    <td><StatusBadge status={m.status} /></td>
                    <td className="num">{ghs(m.cost_pesewas)}</td>
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
