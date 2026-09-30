import { useId } from "react";

const MESSAGE_STATUS = {
  queued: { label: "Queued", tone: "warn" },
  sent: { label: "Sent", tone: "" },
  delivered: { label: "Delivered", tone: "ok" },
  failed: { label: "Failed", tone: "bad" },
  expired: { label: "Expired", tone: "bad" },
};

export function StatusBadge({ status }) {
  const { label, tone } = MESSAGE_STATUS[status] ?? { label: status, tone: "" };
  return <span className={`badge${tone ? ` badge--${tone}` : ""}`}>{label}</span>;
}

export const LEDGER_KIND = {
  topup: "Top-up",
  debit: "Message sent",
  refund: "Refund",
  adjustment: "Adjustment",
};

export function TextField({ label, hint, error, prefix, trailing, id: idProp, ...inputProps }) {
  const autoId = useId();
  const id = idProp || autoId;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = error ? errorId : hint ? hintId : undefined;
  const classes = ["field__input", prefix && "field__input--with-prefix", trailing && "field__input--with-trailing"]
    .filter(Boolean).join(" ");
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>{label}</label>
      <div className="field__control">
        {prefix && <span className="field__prefix" aria-hidden="true">{prefix}</span>}
        <input id={id} className={classes} aria-invalid={error ? "true" : undefined} aria-describedby={describedBy} {...inputProps} />
        {trailing}
      </div>
      {error ? <p id={errorId} className="field__error">{error}</p> : hint ? <p id={hintId} className="field__hint">{hint}</p> : null}
    </div>
  );
}

export function Loading({ label = "Loading…" }) {
  return (
    <p className="state state--loading" role="status">
      <span className="spinner" aria-hidden="true" /> {label}
    </p>
  );
}

export function ErrorNote({ error, onRetry }) {
  return (
    <div className="notice notice--error state" role="alert">
      <p>{error?.message || "Something went wrong."}</p>
      {onRetry && <button type="button" className="btn btn--link" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="empty">
      <h3 className="empty__title">{title}</h3>
      {children && <p className="empty__body">{children}</p>}
      {action}
    </div>
  );
}

export function Pagination({ page, totalPages, onChange, busy = false }) {
  if (!totalPages || totalPages <= 1) return null;
  return (
    <nav className="pager" aria-label="Pagination">
      <button type="button" className="btn btn--outline btn--small" disabled={busy || page <= 1} onClick={() => onChange(page - 1)}>
        Previous
      </button>
      <span className="pager__status" aria-live="polite">Page {page} of {totalPages}</span>
      <button type="button" className="btn btn--outline btn--small" disabled={busy || page >= totalPages} onClick={() => onChange(page + 1)}>
        Next
      </button>
    </nav>
  );
}

export function PageHeader({ title, children }) {
  return (
    <header className="pagehead">
      <h1 className="pagehead__title">{title}</h1>
      {children && <p className="pagehead__lede">{children}</p>}
    </header>
  );
}
