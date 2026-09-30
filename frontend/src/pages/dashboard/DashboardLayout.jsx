import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import DashboardTopbar from "../../components/DashboardTopbar";
import Logo from "../../components/Logo";
import { IconApiKeys, IconBook, IconCart, IconClose, IconEdit, IconMenu, IconMessage, IconOverview, IconUsers, IconWallet } from "../../components/icons";
import "../../styles/dashboard.css";

const NAV = [
  { to: "/dashboard", label: "Overview", icon: IconOverview, end: true },
  { to: "/dashboard/customers", label: "Customers", icon: IconUsers },
  { to: "/dashboard/templates", label: "Templates", icon: IconEdit },
  { to: "/dashboard/api-keys", label: "API keys", icon: IconApiKeys },
  { to: "/dashboard/messages", label: "Messages", icon: IconMessage },
  { to: "/dashboard/wallet", label: "Wallet", icon: IconWallet },
  { to: "/dashboard/plans", label: "Buy SMS", icon: IconCart },
  { to: "/dashboard/quickstart", label: "Quickstart", icon: IconBook },
];

export default function DashboardLayout() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <div className="dash">
      <a className="dash__skip" href="#main">Skip to content</a>

      <header className="dash__topbar on-dark">
        <Logo light to="/dashboard" />
        <button type="button" className="dash__menu" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls="dash-side">
          {open ? <IconClose /> : <IconMenu />}
          <span className="sr-only">{open ? "Close menu" : "Open menu"}</span>
        </button>
      </header>

      <aside id="dash-side" className={`dash__side on-dark${open ? " is-open" : ""}`}>
        <div className="dash__brand"><Logo light to="/dashboard" /></div>
        <nav className="dash__nav" aria-label="Dashboard">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `dash__link${isActive ? " is-active" : ""}`}>
              <Icon /> {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      {open && <button type="button" className="dash__scrim" aria-label="Close menu" onClick={() => setOpen(false)} />}

      <main id="main" className="dash__main" tabIndex={-1}>
        <DashboardTopbar />
        <Outlet />
      </main>
    </div>
  );
}
