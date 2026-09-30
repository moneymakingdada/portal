import { Link } from "react-router-dom";
import { EmptyState, ErrorNote, Loading, PageHeader, StatusBadge } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { formatDateTime, ghs, number } from "../../lib/format";
import { useApi } from "../../lib/useApi";

function DailyBars({ daily }) {
  const max = Math.max(1, ...daily.map((d) => d.count));
  const total = daily.reduce((sum, d) => sum + d.count, 0);
  return (
    <div className="bars" role="img" aria-label={`Messages per day over the last 14 days. ${total} in total.`}>
      {daily.map((d) => {
        const day = new Date(`${d.date}T00:00:00`);
        const label = day.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
        return (
          <div key={d.date} className="bars__col" title={`${label}: ${d.count}`}>
            <span className="bars__value">{d.count > 0 ? d.count : ""}</span>
            <span className="bars__bar" style={{ height: `${Math.max(2, (d.count / max) * 100)}%` }} data-empty={d.count === 0} />
            <span className="bars__label">{day.getDate()}</span>
          </div>
        );
      })}
    </div>
  );
}

function GetStarted({ overview }) {
  const hasKey = overview.active_api_keys > 0;
  const hasSent = overview.messages.total > 0;
  const steps = [
    { done: hasKey, title: "Create a test key", text: "It's free and never sends an SMS.", to: "/dashboard/api-keys", cta: "Create a key" },
    { done: false, title: "Send and check a code", text: "Copy the two requests from the quickstart.", to: "/dashboard/quickstart", cta: "Open quickstart" },
    { done: hasSent, title: "Go live", text: "Add credit, make a live key, and real codes reach real phones.", to: "/dashboard/wallet", cta: "See your wallet" },
  ];
  return (
    <section className="panel" aria-labelledby="get-started">
      <h2 id="get-started" className="panel__title">Get started</h2>
      <ol className="todo">
        {steps.map((s) => (
          <li key={s.title} className={`todo__item${s.done ? " is-done" : ""}`}>
            <span className="todo__mark" aria-hidden="true">{s.done ? "✓" : ""}</span>
            <div>
              <p className="todo__title">{s.title}{s.done && <span className="sr-only"> (done)</span>}</p>
              <p className="todo__text">{s.text}</p>
            </div>
            <Link to={s.to} className="btn btn--outline btn--small">{s.cta}</Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function Overview() {
  const { user } = useAuth();
  const overview = useApi("/dashboard/overview");
  const recent = useApi("/messages?page_size=5");
  const o = overview.data;

  return (
    <>
      <PageHeader title="Overview">{user.organization?.name}</PageHeader>

      {overview.error && <ErrorNote error={overview.error} onRetry={overview.reload} />}
      {!o && overview.loading && <Loading />}

      {o && (
        <>
          <section className="balance on-dark" aria-labelledby="balance-label">
            <div>
              <h2 id="balance-label" className="balance__label">Wallet balance</h2>
              <p className="balance__amount">{ghs(o.balance_pesewas)}</p>
            </div>
            <Link to="/dashboard/wallet" className="btn btn--outline-light btn--small">View ledger</Link>
          </section>

          <dl className="stats">
            <div className="stats__item">
              <dt>Messages, last 30 days</dt>
              <dd>{number(o.messages.total)}</dd>
            </div>
            <div className="stats__item">
              <dt>Delivered or sent</dt>
              <dd>{number(o.messages.delivered + o.messages.sent)}</dd>
            </div>
            <div className="stats__item">
              <dt>Failed</dt>
              <dd>{number(o.messages.failed)}</dd>
            </div>
            <div className="stats__item">
              <dt>Codes verified</dt>
              <dd>{number(o.otp.verified)}<span className="stats__of"> of {number(o.otp.requested)}</span></dd>
            </div>
          </dl>

          {(o.active_api_keys === 0 || o.messages.total === 0) && <GetStarted overview={o} />}

          <section className="panel" aria-labelledby="daily-title">
            <h2 id="daily-title" className="panel__title">Messages per day</h2>
            <DailyBars daily={o.daily} />
          </section>
        </>
      )}

      <section className="panel" aria-labelledby="recent-title">
        <div className="panel__head">
          <h2 id="recent-title" className="panel__title">Recent messages</h2>
          <Link to="/dashboard/messages" className="btn btn--link">All messages</Link>
        </div>
        {recent.error && <ErrorNote error={recent.error} onRetry={recent.reload} />}
        {!recent.data && recent.loading && <Loading />}
        {recent.data && recent.data.results.length === 0 && (
          <EmptyState title="No messages yet">
            Messages appear here when you send with a live key. Test keys never send an SMS, so they aren't listed.
          </EmptyState>
        )}
        {recent.data && recent.data.results.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th scope="col">Time</th><th scope="col">To</th><th scope="col">Status</th><th scope="col" className="num">Cost</th></tr></thead>
              <tbody>
                {recent.data.results.map((m) => (
                  <tr key={m.id}>
                    <td>{formatDateTime(m.created_at)}</td>
                    <td className="mono">{m.recipient}</td>
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
