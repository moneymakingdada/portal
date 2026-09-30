import { Link } from "react-router-dom";
import CodeTabs from "../../components/CodeTabs";
import { PageHeader } from "../../components/ui";
import { publicApiBase } from "../../config";
import { customerMessageSamples, otpSamples } from "../../lib/snippets";

const OTP_ERRORS = [
  ["invalid_api_key", "401", "The key is missing, wrong or revoked."],
  ["invalid_phone", "400", "That isn't a Ghana mobile number."],
  ["cooldown", "429", "A code was sent to this number a moment ago. Wait for Retry-After seconds."],
  ["phone_rate_limited", "429", "Too many codes for this number this hour."],
  ["ip_rate_limited", "429", "Too many codes for this end-user address this hour."],
  ["insufficient_funds", "402", "Your wallet can't cover this message."],
  ["daily_cap_reached", "403", "Your account's daily spend cap was reached."],
  ["invalid_or_expired", "400", "The code was already used, has expired, or the request_id is unknown."],
];

const MESSAGE_ERRORS = [
  ["missing_recipient", "400", "No `to` phone number was given."],
  ["missing_content", "400", "None of template_id, category or message was given."],
  ["invalid_category", "400", "category isn't one of the supported values."],
  ["template_not_found", "400", "template_id doesn't belong to this account."],
  ["sender_not_approved", "400", "sender_id isn't an approved sender for this account."],
  ["insufficient_funds", "402", "Your wallet can't cover this message."],
  ["daily_cap_reached", "403", "Your account's daily spend cap was reached."],
  ["org_rate_limited", "429", "Too many messages sent in a short time."],
];

export default function Quickstart() {
  const base = publicApiBase();
  return (
    <>
      <PageHeader title="Quickstart">
        Two APIs: verification codes, and messages to your own customers. Base URL: <code className="mono">{base}</code>
      </PageHeader>

      <section className="panel" aria-labelledby="qs-samples">
        <h2 id="qs-samples" className="panel__title">Send and check a verification code</h2>
        <p className="panel__text">
          Replace <code className="mono">sk_test_YOUR_KEY</code> with a key from <Link to="/dashboard/api-keys">API keys</Link>.
          With a test key nothing is sent or charged, and a six-digit code is always <code className="mono">123456</code>.
          A wrong code returns <code className="mono">{'{ "verified": false, "attempts_left": 2 }'}</code>. After three wrong
          codes the request is closed, and any later check returns <code className="mono">invalid_or_expired</code>.
        </p>
        <CodeTabs samples={otpSamples({ base })} label="OTP API examples" />
      </section>

      <section className="panel" aria-labelledby="qs-options">
        <h2 id="qs-options" className="panel__title">Options for /otp/send</h2>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th scope="col">Field</th><th scope="col">Default</th><th scope="col">What it does</th></tr></thead>
            <tbody>
              <tr><th scope="row" className="mono">to</th><td>required</td><td>Ghana mobile number in any common format.</td></tr>
              <tr><th scope="row" className="mono">purpose</th><td>empty</td><td>A label such as login or checkout, kept with the request.</td></tr>
              <tr><th scope="row" className="mono">length</th><td>6</td><td>Number of digits, 4 to 8.</td></tr>
              <tr><th scope="row" className="mono">ttl</th><td>300</td><td>Seconds the code stays valid, 60 to 600.</td></tr>
              <tr><th scope="row" className="mono">template</th><td>built in</td><td>Message text. Must contain <code className="mono">{"{code}"}</code>, up to 160 characters.</td></tr>
              <tr><th scope="row" className="mono">client_ip</th><td>none</td><td>Your end user's IP address, for per-user rate limits.</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel" aria-labelledby="qs-messages">
        <h2 id="qs-messages" className="panel__title">Message a customer</h2>
        <p className="panel__text">
          Call this after a sale completes, or any time you want to reach a customer directly — a thank-you,
          a birthday wish, a holiday greeting, or your own words. The phone number becomes a customer on your{" "}
          <Link to="/dashboard/customers">Customers</Link> list automatically, unless you pass{" "}
          <code className="mono">save_customer: false</code>. Birthday messages can also be sent automatically —
          turn that on from the Customers page.
        </p>
        <CodeTabs samples={customerMessageSamples({ base })} label="Customer message API examples" />
      </section>

      <section className="panel" aria-labelledby="qs-message-options">
        <h2 id="qs-message-options" className="panel__title">Options for /messages/send</h2>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th scope="col">Field</th><th scope="col">Default</th><th scope="col">What it does</th></tr></thead>
            <tbody>
              <tr><th scope="row" className="mono">to</th><td>required</td><td>Ghana mobile number in any common format.</td></tr>
              <tr><th scope="row" className="mono">category</th><td>—</td><td>One of thank_you, birthday, holiday, welcome, custom. Uses your saved template for that category, or the built-in suggestion.</td></tr>
              <tr><th scope="row" className="mono">template_id</th><td>—</td><td>Send a specific saved template instead of a category's default.</td></tr>
              <tr><th scope="row" className="mono">message</th><td>—</td><td>Custom text instead of a template. Supports the same placeholders.</td></tr>
              <tr><th scope="row" className="mono">customer_name</th><td>—</td><td>Fills {"{customer_name}"}, and names the customer record if one is created.</td></tr>
              <tr><th scope="row" className="mono">amount</th><td>—</td><td>A number in GHS (e.g. 45.50). Fills {"{amount}"} as "GHS 45.50".</td></tr>
              <tr><th scope="row" className="mono">save_customer</th><td>true</td><td>Whether to create or update a customer record for this phone number.</td></tr>
              <tr><th scope="row" className="mono">sender_id</th><td>—</td><td>An approved sender ID, same as the OTP API.</td></tr>
            </tbody>
          </table>
        </div>
        <p className="panel__text">Provide exactly one of <code className="mono">template_id</code>, <code className="mono">category</code>, or <code className="mono">message</code>.</p>
      </section>

      <section className="panel" aria-labelledby="qs-errors">
        <h2 id="qs-errors" className="panel__title">OTP API errors</h2>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th scope="col">Code</th><th scope="col">Status</th><th scope="col">Meaning</th></tr></thead>
            <tbody>
              {OTP_ERRORS.map(([code, status, text]) => (
                <tr key={code}><th scope="row" className="mono">{code}</th><td>{status}</td><td>{text}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel" aria-labelledby="qs-message-errors">
        <h2 id="qs-message-errors" className="panel__title">Message API errors</h2>
        <p className="panel__text">
          Both APIs return failures the same way: <code className="mono">{'{ "error": { "code": "…", "message": "…" } }'}</code>. Branch on <code className="mono">code</code>, not the message.
        </p>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th scope="col">Code</th><th scope="col">Status</th><th scope="col">Meaning</th></tr></thead>
            <tbody>
              {MESSAGE_ERRORS.map(([code, status, text]) => (
                <tr key={code}><th scope="row" className="mono">{code}</th><td>{status}</td><td>{text}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
