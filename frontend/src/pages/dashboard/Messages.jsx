import { useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorNote, Loading, PageHeader, Pagination, StatusBadge } from "../../components/ui";
import { formatDateTime, ghs } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const FAILURE_REASONS = {
  provider_rejected: "Rejected by the SMS provider",
  provider_unreachable: "SMS provider was unreachable",
  provider_not_configured: "SMS provider isn't configured",
  queue_unavailable: "Couldn't be queued",
};

const CATEGORY_LABELS = {
  otp: "OTP", thank_you: "Thank you", birthday: "Birthday", holiday: "Holiday",
  welcome: "Welcome", custom: "Custom",
};

const STATUS_FILTERS = [
  { value: "", label: "All statuses" },
  { value: "delivered", label: "Delivered" },
  { value: "sent", label: "Sent" },
  { value: "queued", label: "Queued" },
  { value: "failed", label: "Failed" },
];

const CATEGORY_FILTERS = [
  { value: "", label: "All types" },
  { value: "otp", label: "OTP" },
  { value: "thank_you", label: "Thank you" },
  { value: "birthday", label: "Birthday" },
  { value: "holiday", label: "Holiday" },
  { value: "welcome", label: "Welcome" },
  { value: "custom", label: "Custom" },
];

export default function Messages() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const params = new URLSearchParams({ page: String(page) });
  if (status) params.set("status", status);
  if (category) params.set("category", category);
  const { data, error, loading, reload } = useApi(`/messages?${params}`);

  const filtered = Boolean(status || category);

  return (
    <>
      <PageHeader title="Messages">
        Every message sent with a live key — verification codes and customer messages alike.
      </PageHeader>

      <section className="panel" aria-label="Message log">
        <div className="filters">
          <label className="sr-only" htmlFor="status-filter">Status</label>
          <select id="status-filter" className="field__input filters__select" value={status}
            onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            {STATUS_FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
          </select>
          <label className="sr-only" htmlFor="category-filter">Type</label>
          <select id="category-filter" className="field__input filters__select" value={category}
            onChange={(e) => { setCategory(e.target.value); setPage(1); }}>
            {CATEGORY_FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
          </select>
          {data && <span className="filters__count" aria-live="polite">{data.count} {data.count === 1 ? "message" : "messages"}</span>}
        </div>

        {error && <ErrorNote error={error} onRetry={reload} />}
        {!data && loading && <Loading />}
        {data && data.results.length === 0 && (
          <EmptyState title={filtered ? "No messages match these filters" : "No messages yet"}>
            {filtered ? "Try a different filter." : "When you send with a live key, each message shows up here with its status and cost."}
          </EmptyState>
        )}
        {data && data.results.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Time</th><th scope="col">To</th><th scope="col">Type</th>
                  <th scope="col">Status</th><th scope="col" className="num">Segments</th><th scope="col" className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((m) => (
                  <tr key={m.id}>
                    <td>{formatDateTime(m.created_at)}</td>
                    <td className="mono">
                      {m.recipient}
                      {m.customer_id && (
                        <Link to={`/dashboard/customers/${m.customer_id}`} className="table__sub table__sub--link">
                          {m.customer_name || "View customer"}
                        </Link>
                      )}
                    </td>
                    <td>{CATEGORY_LABELS[m.category] || m.category || "—"}</td>
                    <td>
                      <StatusBadge status={m.status} />
                      {m.error_code && <span className="table__sub">{FAILURE_REASONS[m.error_code] || m.error_code}</span>}
                    </td>
                    <td className="num">{m.segments}</td>
                    <td className="num">{ghs(m.cost_pesewas)}</td>
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
