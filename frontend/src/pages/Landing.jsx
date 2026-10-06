import { Link } from "react-router-dom";
import Logo from "../components/Logo";
import CodeTabs from "../components/CodeTabs";
import { APP_NAME } from "../config";
import { useAuth } from "../lib/auth";
import { otpSamples } from "../lib/snippets";
import "../styles/landing.css";

const GROUPS = [
  {
    title: "Sending",
    items: [
      { name: "One-time codes (OTP API)", status: "available", text: "Send a code to a phone number and check what the user types. Codes work once, expire on the timer you set, and lock after three wrong tries." },
      { name: "Email verification", status: "available", text: "The same send-and-check flow for an email address instead of a phone number — same endpoint, channel: \"email\"." },
      { name: "SMS API", status: "available", text: "Send any message — receipts, alerts, reminders — to one number or many at once, through the same key and wallet." },
    ],
  },
  {
    title: "Customer messages",
    items: [
      { name: "Thank-you, birthday, holiday & welcome messages", status: "available", text: "Message a customer after a sale, or any time you like — a suggested message for each occasion, ready to send or customize." },
      { name: "Automatic birthday messages", status: "available", text: "Turn it on once from your Customers page, and every customer gets your birthday message on their day, no API call needed." },
      { name: "Your own templates", status: "available", text: "Keep the suggested wording, or write your own for any category — it's saved as your default from then on." },
      { name: "Sender names", status: "available", text: "Request a name like MYSHOP, or a display name for email, from your Sender IDs page. Each request is reviewed before it's approved." },
    ],
  },
  {
    title: "Your account",
    items: [
      { name: "Dashboard", status: "available", text: "Message volume, delivery status, your customers, API keys, message log and wallet in one place." },
      { name: "Test and live keys", status: "available", text: "Test keys return a fixed code, send nothing and cost nothing. Live keys send real SMS." },
      { name: "Prepaid wallet", status: "available", text: "A balance in cedis with a ledger of every charge, refund and credit." },
      { name: "Mobile Money and card top-ups", status: "soon", text: "Add credit to your wallet yourself, any time." },
    ],
  },
  {
    title: "Protection",
    items: [
      { name: "Rate limits", status: "available", text: "Limits per phone number, per end-user address and per account, so a bot can't turn code or message requests into your bill." },
      { name: "Daily spend cap", status: "available", text: "One ceiling on what an account can spend in a day, shared across verification codes and customer messages." },
      { name: "Automatic refunds", status: "available", text: "If a message can't be sent, it is marked failed and its cost returns to your wallet." },
      { name: "Delivery webhooks", status: "soon", text: "Get a callback on your server when a message is delivered or fails." },
    ],
  },
];

const STEPS = [
  { title: "Create an account", text: "Confirm your mobile number with a code. It's the same flow you'll give your own users." },
  { title: "Make a test key", text: "Create one in the dashboard. It's free and sends no SMS." },
  { title: "Send and check a code", text: "Two calls: /otp/send and /otp/verify. With a test key the code is always 123456." },
  { title: "Go live", text: "Once your wallet has credit, create a live key and swap it in. Codes now reach real phones." },
];

const GHANA = [
  { title: "Numbers as people write them", text: "024 123 4567, 24 123 4567, 233241234567 and +233241234567 all become the same number before anything is sent." },
  { title: "Cedis, counted in pesewas", text: "Prices and balances are in GHS. Every charge is a whole number of pesewas, so the ledger always adds up." },
  { title: "Billed per message segment", text: "One SMS segment holds 160 characters, or 70 if the text has special characters. Longer messages use more segments." },
  { title: "Codes that can't be read back", text: "Codes are stored only as keyed hashes, and the message text in your log has the code masked." },
];

const FAQ = [
  { q: "Do I have to pay to try it?", a: "No. Test keys are free. They return a fixed code (123456 for a six-digit code) and never send an SMS, so you can build the whole flow before spending anything." },
  { q: "Which phone numbers work?", a: "Ghana mobile numbers. Enter them as 024 123 4567, 24 123 4567, 233241234567 or +233241234567 and we convert them to one format." },
  { q: "What happens if a message can't be sent?", a: "It's marked failed in your message log and its cost goes back to your wallet." },
  { q: "How are codes protected?", a: "A code is stored only as a keyed hash, works once, expires after the time you choose (up to 10 minutes) and locks after three wrong attempts. Requests are rate-limited per number, per end-user address and per account." },
  { q: "How do birthday messages work?", a: "Add a customer's birthday, turn on automatic birthday messages from your Customers page, and your birthday template goes out to them once a year without any API call. You can turn it off at any time." },
  { q: "Can messages show my own sender name?", a: "Yes. Request an SMS sender ID or an email display name from your Sender IDs page. Each is reviewed before it can be used — most requests are approved within a day — and you can have one of each." },
];

function Status({ value }) {
  return <span className={`status status--${value}`}>{value === "available" ? "Available" : "Coming soon"}</span>;
}

function Nav() {
  const { status } = useAuth();
  return (
    <nav className="lnav container" aria-label="Main">
      <Logo light />
      <div className="lnav__links">
        <a href="#platform" className="lnav__link">Platform</a>
        <a href="#quickstart" className="lnav__link">Quickstart</a>
        <a href="#faq" className="lnav__link">FAQ</a>
      </div>
      <div className="lnav__actions">
        {status === "authed" ? (
          <Link to="/dashboard" className="btn btn--gold btn--small">Open dashboard</Link>
        ) : (
          <>
            <Link to="/login" className="btn btn--outline-light btn--small">Log in</Link>
            <Link to="/signup" className="btn btn--gold btn--small">Create account</Link>
          </>
        )}
      </div>
    </nav>
  );
}

function Exchange() {
  const code = "482917";
  return (
    <div className="exchange" role="group" aria-label="Example: send a code, it arrives by SMS, check it">
      <div className="exchange__step">
        <p className="exchange__label">Your server sends</p>
        <pre className="exchange__code"><code>{`POST /api/v1/otp/send\n{ "to": "024 123 4567" }`}</code></pre>
      </div>
      <div className="exchange__step">
        <p className="exchange__label">Their phone receives</p>
        <div className="sms">
          <p className="sms__from">{APP_NAME}</p>
          <p className="sms__body">
            Your verification code is{" "}
            <span className="sms__code" role="img" aria-label={[...code].join(" ")}>
              {[...code].map((digit, i) => (
                <span key={i} className="sms__digit" style={{ "--i": i }} aria-hidden="true">{digit}</span>
              ))}
            </span>
            . It expires soon. Never share it.
          </p>
        </div>
      </div>
      <div className="exchange__step exchange__step--last">
        <p className="exchange__label">Your server checks</p>
        <pre className="exchange__code"><code>{`POST /api/v1/otp/verify\n{ "request_id": "6f1c…", "code": "482917" }`}</code></pre>
        <p className="exchange__result">{`{ "verified": true }`}</p>
      </div>
    </div>
  );
}

export default function Landing() {
  const { status } = useAuth();
  const samples = otpSamples();

  return (
    <div className="landing">
      <header className="hero on-dark">
        <Nav />
        <div className="hero__grid container">
          <div className="hero__copy">
            <h1 className="hero__title">Confirm a phone number, then keep in touch with the person behind it.</h1>
            <p className="hero__lede">
              Send a one-time code by SMS to verify a number, or message an existing customer — a thank-you after
              a sale, a birthday wish, a holiday greeting. One dashboard shows every message, customer and cedi
              spent. Build against free test keys, then go live from a prepaid wallet.
            </p>
            <div className="hero__actions">
              {status === "authed" ? (
                <Link to="/dashboard" className="btn btn--gold">Open your dashboard</Link>
              ) : (
                <Link to="/signup" className="btn btn--gold">Create an account</Link>
              )}
              <a href="#quickstart" className="btn btn--outline-light">Read the quickstart</a>
            </div>
            <p className="hero__note">Test keys are free and never send an SMS.</p>
          </div>
          <Exchange />
        </div>
      </header>

      <main>
        <section id="platform" className="section">
          <div className="container platform">
            <div className="platform__intro">
              <h2 className="section__title">Everything in the platform</h2>
              <p className="section__lede">
                What you can use today and what's coming next. Anything marked Available is running now and
                appears in your dashboard.
              </p>
            </div>
            <div className="platform__groups">
              {GROUPS.map((group, index) => (
                <section key={group.title} className="pgroup" aria-labelledby={`platform-group-${index}`}>
                  <h3 id={`platform-group-${index}`} className="pgroup__title">{group.title}</h3>
                  <dl className="pgroup__list">
                    {group.items.map((item) => (
                      <div key={item.name} className="pitem">
                        <dt className="pitem__name">
                          {item.name}
                          <Status value={item.status} />
                        </dt>
                        <dd className="pitem__text">{item.text}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              ))}
            </div>
          </div>
        </section>

        <section id="how" className="section section--paper">
          <div className="container">
            <h2 className="section__title">From sign-up to live codes</h2>
            <ol className="steps">
              {STEPS.map((step, i) => (
                <li key={step.title} className="step">
                  <span className="step__num" aria-hidden="true">{i + 1}</span>
                  <h3 className="step__title">{step.title}</h3>
                  <p className="step__text">{step.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="quickstart" className="section">
          <div className="container quick">
            <div className="quick__copy">
              <h2 className="section__title">Two calls, any language</h2>
              <p className="section__lede">
                Send with a key from your dashboard, then check the code your user typed. Every error comes back in
                the same shape, with a code your app can act on.
              </p>
              <ul className="quick__points">
                <li>Write numbers any way you like; we convert them.</li>
                <li>Pass <code>client_ip</code> with the end user's address to get per-user limits.</li>
                <li>Create keys in the dashboard: <code>sk_test_…</code> or <code>sk_live_…</code>.</li>
              </ul>
            </div>
            <CodeTabs samples={samples} label="OTP API examples" />
          </div>
        </section>

        <section id="ghana" className="section section--paper">
          <div className="container ghana">
            <h2 className="section__title">Made for how Ghana sends and pays</h2>
            <dl className="ghana__list">
              {GHANA.map((item) => (
                <div key={item.title} className="ghana__item">
                  <dt className="ghana__title">{item.title}</dt>
                  <dd className="ghana__text">{item.text}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section id="faq" className="section">
          <div className="container faq">
            <h2 className="section__title">Questions</h2>
            <div className="faq__list">
              {FAQ.map((item) => (
                <details key={item.q} className="faq__item">
                  <summary className="faq__q">{item.q}</summary>
                  <p className="faq__a">{item.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="cta on-dark">
          <div className="container cta__inner">
            <h2 className="cta__title">Build the flow on a test key today.</h2>
            <div className="cta__actions">
              <Link to={status === "authed" ? "/dashboard" : "/signup"} className="btn btn--gold">
                {status === "authed" ? "Open your dashboard" : "Create an account"}
              </Link>
              {status !== "authed" && <Link to="/login" className="btn btn--outline-light">Log in</Link>}
            </div>
          </div>
        </section>
      </main>

      <footer className="lfoot on-dark">
        <div className="container lfoot__inner">
          <Logo light />
          <nav className="lfoot__links" aria-label="Footer">
            <a href="#quickstart">Quickstart</a>
            <a href="#faq">FAQ</a>
            <Link to="/login">Log in</Link>
            <Link to="/signup">Create account</Link>
          </nav>
          <p className="lfoot__copy">© {new Date().getFullYear()} {APP_NAME}</p>
        </div>
      </footer>
    </div>
  );
}