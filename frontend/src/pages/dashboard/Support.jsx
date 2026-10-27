import { EmptyState, ErrorNote, Loading, PageHeader } from "../../components/ui";
import TicketForm from "../../components/TicketForm";
import { formatDateTime } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const STATUS = { open: ["Open", "warn"], answered: ["Answered", "ok"], closed: ["Closed", ""] };

function TicketBadge({ status }) {
  const [label, tone] = STATUS[status] ?? [status, ""];
  return <span className={`badge${tone ? ` badge--${tone}` : ""}`}>{label}</span>;
}

export default function Support() {
  const { data, error, loading, reload } = useApi("/support/tickets");
  const tickets = data?.results ?? [];

  return (
    <>
      <PageHeader title="Support">
        Something wrong? Send it to our team. We reply here and by SMS to the phone number on your account.
        For a quick answer, try the Help chat at the bottom right first.
      </PageHeader>

      <section className="panel" aria-labelledby="new-ticket-title">
        <h2 id="new-ticket-title" className="panel__title">Send a message to our team</h2>
        <TicketForm onCreated={reload} />
      </section>

      <section className="panel" aria-labelledby="tickets-title">
        <h2 id="tickets-title" className="panel__title">Your tickets</h2>
        {loading && !data ? <Loading /> : error ? <ErrorNote error={error} onRetry={reload} /> : tickets.length === 0 ? (
          <EmptyState title="No tickets yet">When you send something to our team, it and our reply will appear here.</EmptyState>
        ) : (
          <ul className="tickets">
            {tickets.map((t) => (
              <li key={t.id} className="ticket">
                <div className="ticket__head">
                  <h3 className="ticket__subject">#{t.id} {t.subject}</h3>
                  <TicketBadge status={t.status} />
                </div>
                <p className="ticket__meta">Sent {formatDateTime(t.created_at)}</p>
                <p className="ticket__text">{t.details}</p>
                {t.staff_reply && (
                  <div className="ticket__reply">
                    <p className="ticket__meta">Our reply{t.replied_at ? `, ${formatDateTime(t.replied_at)}` : ""}</p>
                    <p className="ticket__text">{t.staff_reply}</p>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
