import { Link } from "react-router-dom";
import { EmptyState, ErrorNote, Loading, PageHeader } from "../../components/ui";
import { useCheckout } from "../../lib/checkout";
import { ghs, number } from "../../lib/format";
import { useApi } from "../../lib/useApi";

export default function Plans() {
  const { data, error, loading, reload } = useApi("/plans");
  const checkout = useCheckout();
  const plans = data?.results ?? [];

  return (
    <>
      <PageHeader title="Buy SMS">
        Pick a plan and pay securely with Paystack. The credit lands in your wallet as soon as the payment is confirmed.
      </PageHeader>

      <section className="panel" aria-labelledby="plans-title">
        <h2 id="plans-title" className="panel__title">SMS plans</h2>

        {error && <ErrorNote error={error} onRetry={reload} />}
        {checkout.error && <div className="notice notice--error" role="alert">{checkout.error.message}</div>}
        {!data && loading && <Loading />}
        {data && plans.length === 0 && (
          <EmptyState title="No plans available yet"
            action={<Link to="/dashboard/wallet" className="btn btn--forest btn--small">Top up with any amount</Link>}>
            You can still add credit to your wallet with an amount of your choice.
          </EmptyState>
        )}
        {plans.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Plan name</th>
                  <th scope="col" className="num">Messages</th>
                  <th scope="col" className="num">Price</th>
                  <th scope="col">Popular</th>
                  <th scope="col"><span className="sr-only">Buy</span></th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan, index) => (
                  <tr key={plan.id}>
                    <td>{index + 1}</td>
                    <th scope="row" className="table__name">{plan.name}</th>
                    <td className="num">{number(plan.message_count)}</td>
                    <td className="num">{ghs(plan.price_pesewas)}</td>
                    <td>{plan.is_popular ? <span className="badge badge--ok badge--plain">Yes</span> : "No"}</td>
                    <td className="table__actions">
                      <button type="button" className="btn btn--forest btn--small"
                        disabled={checkout.busyKey !== null}
                        onClick={() => checkout.start({ plan_id: plan.id }, plan.id)}>
                        {checkout.busyKey === plan.id ? "Opening Paystack…" : "Buy with Paystack"}
                        <span className="sr-only"> {plan.name}</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="panel__text panel__text--after">
          Message counts are for standard-length messages (up to 160 characters). Prefer a different amount?{" "}
          <Link to="/dashboard/wallet">Top up your wallet with any amount.</Link>
        </p>
      </section>
    </>
  );
}
