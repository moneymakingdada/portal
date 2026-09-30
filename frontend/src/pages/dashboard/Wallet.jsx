import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { EmptyState, ErrorNote, LEDGER_KIND, Loading, PageHeader, Pagination, TextField } from "../../components/ui";
import { api } from "../../lib/api";
import { useCheckout } from "../../lib/checkout";
import { formatDateTime, ghs, number, signedGhs } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { notifyWalletChanged } from "../../lib/walletEvents";

/** What to tell someone who has just come back from Paystack's checkout page. */
function PaymentResult({ result, onCheckAgain, checking }) {
  if (!result) return null;
  return (
    <div className={`notice notice--${result.tone} paymentresult`} role={result.tone === "error" ? "alert" : "status"}>
      <p>{result.message}</p>
      {result.retry && (
        <button type="button" className="btn btn--link" onClick={onCheckAgain} disabled={checking}>
          {checking ? "Checking…" : "Check again"}
        </button>
      )}
    </div>
  );
}

function TopUpForm() {
  const [amount, setAmount] = useState("");
  const checkout = useCheckout();
  const valid = Number(amount) > 0;

  function submit(event) {
    event.preventDefault();
    if (valid) checkout.start({ amount }, "custom");
  }

  return (
    <form className="topup" onSubmit={submit} noValidate>
      <TextField label="Amount (GHS)" name="amount" type="number" inputMode="decimal" min="0" step="0.01"
        placeholder="50.00" value={amount} onChange={(e) => setAmount(e.target.value)}
        hint="You'll pay on Paystack's secure checkout page." />
      <button type="submit" className="btn btn--forest" disabled={!valid || checkout.busyKey !== null}>
        {checkout.busyKey ? "Opening Paystack…" : "Pay with Paystack"}
      </button>
      {checkout.error && <div className="notice notice--error topup__error" role="alert">{checkout.error.message}</div>}
    </form>
  );
}

export default function Wallet() {
  const [page, setPage] = useState(1);
  const wallet = useApi("/wallet");
  const ledger = useApi(`/wallet/ledger?page=${page}`);
  const [searchParams, setSearchParams] = useSearchParams();
  const [result, setResult] = useState(null);
  const [pendingRef, setPendingRef] = useState(null);
  const [checking, setChecking] = useState(false);
  const handled = useRef(null);

  const checkPayment = useCallback(async (reference) => {
    setChecking(true);
    try {
      const r = await api.get(`/wallet/topup/verify?reference=${encodeURIComponent(reference)}`);
      if (r.status === "success") {
        setPendingRef(null);
        setResult({ tone: "ok", message: `Payment received. ${ghs(r.amount_pesewas)} was added to your wallet.` });
        wallet.reload();
        ledger.reload();
        notifyWalletChanged();
      } else if (r.status === "pending") {
        setPendingRef(reference);
        setResult({
          tone: "info", retry: true,
          message: "We haven't had confirmation of that payment yet. If you completed it, your balance will update shortly.",
        });
      } else {
        setPendingRef(null);
        setResult({
          tone: "error",
          message: `That payment wasn't completed. If you were charged, contact support and quote reference ${reference}.`,
        });
      }
    } catch (err) {
      setPendingRef(reference);
      setResult({ tone: "error", retry: true, message: err.message });
    } finally {
      setChecking(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Paystack sends people back here with ?reference=... after they pay (or give up).
  const reference = searchParams.get("reference");
  useEffect(() => {
    if (!reference || handled.current === reference) return;
    handled.current = reference;
    setSearchParams({}, { replace: true });   // tidy the address bar (also drops Paystack's trxref)
    checkPayment(reference);
  }, [reference, setSearchParams, checkPayment]);

  return (
    <>
      <PageHeader title="Wallet">
        Live messages are charged from this prepaid balance. Every charge, refund and credit is a line in the ledger below.
      </PageHeader>

      <PaymentResult result={result} checking={checking} onCheckAgain={() => checkPayment(pendingRef)} />

      {wallet.error && <ErrorNote error={wallet.error} onRetry={wallet.reload} />}
      {!wallet.data && wallet.loading && <Loading />}
      {wallet.data && (
        <section className="balance on-dark" aria-labelledby="wallet-balance">
          <div>
            <h2 id="wallet-balance" className="balance__label">Balance</h2>
            <p className="balance__amount">{ghs(wallet.data.balance_pesewas)}</p>
            <p className="balance__sub">About {number(wallet.data.sms_balance)} standard messages</p>
          </div>
          <Link to="/dashboard/plans" className="btn btn--outline-light btn--small">Buy an SMS plan</Link>
        </section>
      )}

      <section className="panel" aria-labelledby="topup-title">
        <h2 id="topup-title" className="panel__title">Top up</h2>
        <p className="panel__text">Add any amount, or pick a ready-made <Link to="/dashboard/plans">SMS plan</Link>.</p>
        <TopUpForm />
      </section>

      <section className="panel" aria-labelledby="ledger-title">
        <h2 id="ledger-title" className="panel__title">Ledger</h2>
        {ledger.error && <ErrorNote error={ledger.error} onRetry={ledger.reload} />}
        {!ledger.data && ledger.loading && <Loading />}
        {ledger.data && ledger.data.results.length === 0 && (
          <EmptyState title="Nothing here yet">Credits, charges and refunds will be listed here.</EmptyState>
        )}
        {ledger.data && ledger.data.results.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Time</th><th scope="col">Type</th><th scope="col">Note</th>
                  <th scope="col" className="num">Amount</th><th scope="col" className="num">Balance after</th>
                </tr>
              </thead>
              <tbody>
                {ledger.data.results.map((e) => (
                  <tr key={e.id}>
                    <td>{formatDateTime(e.created_at)}</td>
                    <td>{LEDGER_KIND[e.kind] || e.kind}</td>
                    <td className="table__note">{e.note || "—"}</td>
                    <td className={`num amount ${e.amount_pesewas < 0 ? "amount--out" : "amount--in"}`}>{signedGhs(e.amount_pesewas)}</td>
                    <td className="num">{ghs(e.balance_after_pesewas)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {ledger.data && <Pagination page={ledger.data.page} totalPages={ledger.data.total_pages} onChange={setPage} busy={ledger.loading} />}
      </section>
    </>
  );
}
