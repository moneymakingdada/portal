import { useEffect } from "react";
import { Link } from "react-router-dom";
import Logo from "../../components/Logo";
import { APP_NAME } from "../../config";
import { COMPANY, LEGAL_UPDATED } from "../../lib/legal";
import "../../styles/legal.css";

/** Where to reach us, using only the details that have been configured. */
export function ContactDetails() {
  return (
    <p>
      {COMPANY.email
        ? <>Email <a href={`mailto:${COMPANY.email}`}>{COMPANY.email}</a>.</>
        : <>Use the support contact shown on our website.</>}
      {COMPANY.address && <> Our address is {COMPANY.address}.</>}
    </p>
  );
}

export default function LegalLayout({ title, summary, sections }) {
  useEffect(() => {
    const previous = document.title;
    document.title = `${title} · ${APP_NAME}`;
    return () => { document.title = previous; };
  }, [title]);

  return (
    <div className="legal">
      <header className="legal__bar">
        <Logo />
        <nav aria-label="Account" className="legal__bar-links">
          <Link to="/login">Log in</Link>
          <Link to="/signup" className="btn btn--forest btn--small">Create account</Link>
        </nav>
      </header>

      <main id="main" className="legal__doc">
        <h1>{title}</h1>
        <p className="legal__meta">Last updated {LEGAL_UPDATED}</p>
        <p className="legal__summary"><strong>In short:</strong> {summary}</p>

        <nav aria-label="Contents" className="legal__toc">
          <h2 className="legal__toc-title">Contents</h2>
          <ol>
            {sections.map((s) => <li key={s.id}><a href={`#${s.id}`}>{s.title}</a></li>)}
          </ol>
        </nav>

        <div className="legal__body">
          {sections.map((s) => (
            <section key={s.id} id={s.id} className="legal__section" aria-labelledby={`${s.id}-title`}>
              <h2 id={`${s.id}-title`}>{s.title}</h2>
              {s.body}
            </section>
          ))}
        </div>
      </main>

      <footer className="legal__foot">
        <nav aria-label="Legal">
          <Link to="/terms">Terms of Service</Link>
          <Link to="/privacy">Privacy Policy</Link>
          <Link to="/">Home</Link>
        </nav>
        <p>© {new Date().getFullYear()} {COMPANY.name}</p>
      </footer>
    </div>
  );
}
