import Logo from "../components/Logo";
import "../styles/auth.css";

export default function AuthLayout({ title, subtitle, children, footer }) {
  return (
    <div className="auth">
      <aside className="auth__aside on-dark">
        <Logo light />
        <div className="auth__pitch">
          <p className="auth__pitch-title">Confirm a phone number in the time it takes to read a text.</p>
          <ul className="auth__points">
            <li>Free test keys: no SMS is sent and nothing is charged.</li>
            <li>Ghana numbers in any format: 024…, 233… or +233…</li>
            <li>A prepaid GHS wallet with a ledger you can read line by line.</li>
          </ul>
        </div>
        <p className="auth__aside-foot">Phone verification for apps in Ghana.</p>
      </aside>

      <main className="auth__main">
        <div className="auth__mobile-logo"><Logo /></div>
        <div className="auth__panel">
          <h1 className="auth__title">{title}</h1>
          {subtitle && <p className="auth__subtitle">{subtitle}</p>}
          {children}
          {footer && <p className="auth__footer">{footer}</p>}
        </div>
      </main>
    </div>
  );
}
