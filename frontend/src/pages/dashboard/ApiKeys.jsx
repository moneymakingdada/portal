import { useEffect, useRef, useState } from "react";
import { EmptyState, ErrorNote, Loading, PageHeader, TextField } from "../../components/ui";
import { IconCheck, IconCopy } from "../../components/icons";
import { api, fieldError } from "../../lib/api";
import { copyText, formatDate } from "../../lib/format";
import { useApi } from "../../lib/useApi";

function NewKeyReveal({ created, onDismiss }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    if (await copyText(created.secret)) {
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1800);
    }
  };

  return (
    <section className="reveal" aria-labelledby="reveal-title">
      <h2 id="reveal-title" className="reveal__title">Copy your new key now</h2>
      <p className="reveal__text">
        This is the only time the full key is shown. Store it somewhere safe, like your server's environment variables.
      </p>
      <div className="reveal__row">
        <code className="reveal__key" data-testid="new-key-secret">{created.secret}</code>
        <button type="button" className="btn btn--forest btn--small" onClick={copy}>
          {copied ? <IconCheck width={16} height={16} /> : <IconCopy width={16} height={16} />}
          <span aria-live="polite">{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      <button type="button" className="btn btn--link" onClick={onDismiss}>I've saved it</button>
    </section>
  );
}

export default function ApiKeys() {
  const { data, error, loading, reload } = useApi("/api-keys");
  const [name, setName] = useState("");
  const [live, setLive] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);
  const [created, setCreated] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [actionError, setActionError] = useState(null);

  async function create(event) {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      const result = await api.post("/api-keys", { name: name.trim(), live });
      setCreated(result);
      setName("");
      reload();
    } catch (err) {
      setCreateError(err);
    } finally {
      setCreating(false);
    }
  }

  async function revoke(id) {
    setActionError(null);
    try {
      await api.delete(`/api-keys/${id}`);
      setConfirming(null);
      reload();
    } catch (err) {
      setActionError(err);
    }
  }

  const keys = data?.results ?? [];
  const nameError = fieldError(createError, "name");
  const formError = createError && createError.code !== "validation_error" ? createError.message : null;

  return (
    <>
      <PageHeader title="API keys">
        Keys let your server call the API. Test keys are free and send no SMS; live keys send real messages and spend from your wallet.
      </PageHeader>

      {created && <NewKeyReveal created={created} onDismiss={() => setCreated(null)} />}

      <section className="panel" aria-labelledby="create-key-title">
        <h2 id="create-key-title" className="panel__title">Create a key</h2>
        <form className="keyform" onSubmit={create} noValidate>
          <TextField label="Name" name="key_name" placeholder="e.g. Checkout backend" maxLength={60} required
            value={name} onChange={(e) => setName(e.target.value)} error={nameError} />
          <fieldset className="mode">
            <legend className="field__label">Mode</legend>
            <label className={`mode__option${!live ? " is-selected" : ""}`}>
              <input type="radio" name="mode" checked={!live} onChange={() => setLive(false)} />
              <span><strong>Test</strong> Free. Fixed code, no SMS.</span>
            </label>
            <label className={`mode__option${live ? " is-selected" : ""}`}>
              <input type="radio" name="mode" checked={live} onChange={() => setLive(true)} />
              <span><strong>Live</strong> Sends real SMS.</span>
            </label>
          </fieldset>
          <button type="submit" className="btn btn--forest" disabled={creating || !name.trim()}>
            {creating ? "Creating…" : "Create key"}
          </button>
        </form>
        {formError && <div className="notice notice--error" role="alert">{formError}</div>}
      </section>

      <section className="panel" aria-labelledby="keys-title">
        <h2 id="keys-title" className="panel__title">Your keys</h2>
        {error && <ErrorNote error={error} onRetry={reload} />}
        {actionError && <div className="notice notice--error" role="alert">{actionError.message}</div>}
        {!data && loading && <Loading />}
        {data && keys.length === 0 && <EmptyState title="No keys yet">Create a test key above to start building.</EmptyState>}
        {keys.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th><th scope="col">Mode</th><th scope="col">Key</th>
                  <th scope="col">Created</th><th scope="col">Last used</th><th scope="col">Status</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => {
                  const revoked = Boolean(k.revoked_at);
                  return (
                    <tr key={k.id} className={revoked ? "is-muted" : undefined}>
                      <th scope="row" className="table__name">{k.name}</th>
                      <td><span className={`badge badge--plain ${k.is_live ? "badge--ok" : ""}`}>{k.is_live ? "Live" : "Test"}</span></td>
                      <td className="mono">{k.prefix}…</td>
                      <td>{formatDate(k.created_at)}</td>
                      <td>{k.last_used_at ? formatDate(k.last_used_at) : "Never"}</td>
                      <td>{revoked ? <span className="badge badge--bad">Revoked</span> : <span className="badge badge--ok">Active</span>}</td>
                      <td className="table__actions">
                        {!revoked && (confirming === k.id ? (
                          <span className="confirm">
                            <span>Revoke this key?</span>
                            <button type="button" className="btn btn--danger btn--small" onClick={() => revoke(k.id)}>Revoke</button>
                            <button type="button" className="btn btn--outline btn--small" onClick={() => setConfirming(null)}>Keep</button>
                          </span>
                        ) : (
                          <button type="button" className="btn btn--outline btn--small" onClick={() => setConfirming(k.id)}>
                            Revoke<span className="sr-only"> {k.name}</span>
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
      </section>
    </>
  );
}
