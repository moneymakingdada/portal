import { useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorNote, Loading, PageHeader, Pagination, TextField } from "../../components/ui";
import { api, fieldError } from "../../lib/api";
import { formatDate } from "../../lib/format";
import { useApi } from "../../lib/useApi";

function BirthdayToggle() {
  const { data, error, loading, reload } = useApi("/settings");
  const [saving, setSaving] = useState(false);

  async function setEnabled(next) {
    setSaving(true);
    try {
      await api.patch("/settings", { birthday_messages_enabled: next });
    } finally {
      setSaving(false);
      reload();
    }
  }

  if (error) return null; // non-essential panel: fail quietly rather than blocking the page
  if (!data && loading) return null;

  return (
    <section className="panel panel--tight" aria-labelledby="birthday-toggle-title">
      <div className="toggle-row">
        <div>
          <h2 id="birthday-toggle-title" className="panel__title panel__title--small">Automatic birthday messages</h2>
          <p className="panel__text panel__text--tight">
            Send your birthday template to a customer automatically on their birthday, once a day.
          </p>
        </div>
        <label className="switch">
          <input
            type="checkbox"
            checked={Boolean(data?.birthday_messages_enabled)}
            disabled={saving}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          <span className="switch__track"><span className="switch__thumb" /></span>
          <span className="sr-only">Toggle automatic birthday messages</span>
        </label>
      </div>
    </section>
  );
}

function AddCustomerForm({ onCreated }) {
  const [form, setForm] = useState({ name: "", phone: "", email: "", birthday: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (name) => (e) => setForm((f) => ({ ...f, [name]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload = { ...form, birthday: form.birthday || null };
      const customer = await api.post("/customers", payload);
      setForm({ name: "", phone: "", email: "", birthday: "" });
      onCreated(customer);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="customerform" onSubmit={submit} noValidate>
      <TextField label="Name" name="name" value={form.name} onChange={set("name")}
        error={fieldError(error, "name")} />
      <TextField label="Phone" name="phone" type="tel" placeholder="024 123 4567" required
        value={form.phone} onChange={set("phone")} error={fieldError(error, "phone")} />
      <TextField label="Email (optional)" name="email" type="email" value={form.email} onChange={set("email")}
        error={fieldError(error, "email")} />
      <TextField label="Birthday (optional)" name="birthday" type="date" value={form.birthday}
        onChange={set("birthday")} error={fieldError(error, "birthday")} />
      <button type="submit" className="btn btn--forest" disabled={busy || !form.phone.trim()}>
        {busy ? "Adding…" : "Add customer"}
      </button>
      {error && error.code !== "validation_error" && (
        <div className="notice notice--error" role="alert">{error.message}</div>
      )}
    </form>
  );
}

export default function Customers() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const query = `/customers?page=${page}${search ? `&search=${encodeURIComponent(search)}` : ""}`;
  const { data, error, loading, reload } = useApi(query);

  return (
    <>
      <PageHeader title="Customers">
        The people you do business with. Message them a thank-you, a birthday wish, or your own note.
      </PageHeader>

      <BirthdayToggle />

      <section className="panel" aria-labelledby="customers-title">
        <div className="panel__head">
          <h2 id="customers-title" className="panel__title">Your customers</h2>
          <button type="button" className="btn btn--outline btn--small" onClick={() => setAdding((a) => !a)}>
            {adding ? "Close" : "Add customer"}
          </button>
        </div>

        {adding && (
          <AddCustomerForm onCreated={() => { setAdding(false); reload(); }} />
        )}

        <div className="filters">
          <TextField label="Search" name="search" placeholder="Name or phone number"
            value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        </div>

        {error && <ErrorNote error={error} onRetry={reload} />}
        {!data && loading && <Loading />}
        {data && data.results.length === 0 && (
          <EmptyState title={search ? "No matching customers" : "No customers yet"}>
            {search ? "Try a different search." : "Add your first customer above, or they'll appear here automatically the first time you message a new phone number."}
          </EmptyState>
        )}
        {data && data.results.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th scope="col">Name</th><th scope="col">Phone</th><th scope="col">Birthday</th><th scope="col">Added</th><th scope="col"><span className="sr-only">View</span></th></tr></thead>
              <tbody>
                {data.results.map((c) => (
                  <tr key={c.id}>
                    <th scope="row" className="table__name">{c.name || "—"}</th>
                    <td className="mono">{c.phone}</td>
                    <td>{c.birthday ? formatDate(c.birthday) : "—"}</td>
                    <td>{formatDate(c.created_at)}</td>
                    <td className="table__actions">
                      <Link to={`/dashboard/customers/${c.id}`} className="btn btn--outline btn--small">Open</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pagination page={data.page} totalPages={data.total_pages} onChange={setPage} busy={loading} />}
      </section>
    </>
  );
}
