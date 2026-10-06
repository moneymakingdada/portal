import { useState } from "react";
import { EmptyState, ErrorNote, Loading, PageHeader, TextField } from "../../components/ui";
import { api, fieldError } from "../../lib/api";
import { formatDate } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const STATUS_LABEL = { pending: "Pending review", approved: "Approved", rejected: "Rejected" };
const STATUS_TONE = { pending: "warn", approved: "ok", rejected: "bad" };

function RequestForm({ onCreated }) {
  const [channel, setChannel] = useState("sms");
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.post("/sender-ids", { channel, name: name.trim(), purpose: purpose.trim() });
      setName("");
      setPurpose("");
      onCreated(created);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="keyform senderform" onSubmit={submit} noValidate>
      <fieldset className="mode">
        <legend className="field__label">Type</legend>
        <label className={`mode__option${channel === "sms" ? " is-selected" : ""}`}>
          <input type="radio" name="channel" checked={channel === "sms"} onChange={() => setChannel("sms")} />
          <span><strong>SMS sender ID</strong> Up to 11 letters and numbers, e.g. ADOMSHOP.</span>
        </label>
        <label className={`mode__option${channel === "email" ? " is-selected" : ""}`}>
          <input type="radio" name="channel" checked={channel === "email"} onChange={() => setChannel("email")} />
          <span><strong>Email display name</strong> Shown as the "From" name, e.g. Adom Bakery.</span>
        </label>
      </fieldset>

      <TextField label="Name" name="sender_name" maxLength={channel === "sms" ? 11 : 160}
        placeholder={channel === "sms" ? "ADOMSHOP" : "Adom Bakery"} required
        value={name} onChange={(e) => setName(e.target.value)} error={fieldError(error, "name")}
        hint={channel === "sms" ? `${name.length}/11 characters` : undefined} />

      <TextField label="What will you send with it? (optional)" name="purpose"
        placeholder="e.g. order confirmations and delivery updates"
        value={purpose} onChange={(e) => setPurpose(e.target.value)} error={fieldError(error, "purpose")} />

      <button type="submit" className="btn btn--forest" disabled={busy || !name.trim()}>
        {busy ? "Submitting…" : "Request approval"}
      </button>
      {error && error.code !== "validation_error" && (
        <div className="notice notice--error" role="alert">{error.message}</div>
      )}
    </form>
  );
}

export default function SenderIds() {
  const { data, error, loading, reload } = useApi("/sender-ids");
  const [withdrawing, setWithdrawing] = useState(null);
  const [actionError, setActionError] = useState(null);

  async function withdraw(id) {
    setActionError(null);
    try {
      await api.delete(`/sender-ids/${id}`);
      setWithdrawing(null);
      reload();
    } catch (err) {
      setActionError(err);
    }
  }

  const requests = data?.results ?? [];

  return (
    <>
      <PageHeader title="Sender IDs">
        Request a custom name for your SMS and email, so recipients see your brand instead of the platform
        default. Each request is reviewed before it can be used — pass the approved name as{" "}
        <code className="mono">sender_id</code> on any send.
      </PageHeader>

      <section className="panel" aria-labelledby="request-title">
        <h2 id="request-title" className="panel__title">Request a sender ID</h2>
        <RequestForm onCreated={reload} />
      </section>

      <section className="panel" aria-labelledby="requests-title">
        <h2 id="requests-title" className="panel__title">Your requests</h2>
        {error && <ErrorNote error={error} onRetry={reload} />}
        {actionError && <div className="notice notice--error" role="alert">{actionError.message}</div>}
        {!data && loading && <Loading />}
        {data && requests.length === 0 && (
          <EmptyState title="No requests yet">Request one above — most are reviewed within a day.</EmptyState>
        )}
        {requests.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th><th scope="col">Type</th><th scope="col">Status</th>
                  <th scope="col">Requested</th><th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {requests.map((s) => (
                  <tr key={s.id}>
                    <th scope="row" className="table__name mono">{s.name}</th>
                    <td>{s.channel === "email" ? "Email" : "SMS"}</td>
                    <td>
                      <span className={`badge badge--${STATUS_TONE[s.status]}`}>{STATUS_LABEL[s.status]}</span>
                      {s.status === "rejected" && s.rejection_reason && (
                        <span className="table__sub">{s.rejection_reason}</span>
                      )}
                    </td>
                    <td>{formatDate(s.created_at)}</td>
                    <td className="table__actions">
                      {s.status === "pending" && (withdrawing === s.id ? (
                        <span className="confirm">
                          <span>Withdraw?</span>
                          <button type="button" className="btn btn--danger btn--small" onClick={() => withdraw(s.id)}>Withdraw</button>
                          <button type="button" className="btn btn--outline btn--small" onClick={() => setWithdrawing(null)}>Keep</button>
                        </span>
                      ) : (
                        <button type="button" className="btn btn--outline btn--small" onClick={() => setWithdrawing(s.id)}>
                          Withdraw<span className="sr-only"> {s.name}</span>
                        </button>
                      ))}
                    </td>
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