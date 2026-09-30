import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ghs, number } from "../lib/format";
import { useApi } from "../lib/useApi";
import { onWalletChanged } from "../lib/walletEvents";
import { IconLogout, IconMessage, IconWallet } from "./icons";

/** Balances and the account menu, shown above every dashboard page. */
export default function DashboardTopbar() {
  const { user, signOut } = useAuth();
  const { data, reload } = useApi("/wallet"); // fails quietly: a stale/missing balance shouldn't block the page
  useEffect(() => onWalletChanged(reload), [reload]);

  return (
    <header className="dashtop">
      <div className="dashtop__balances">
        <Link to="/dashboard/wallet" className="dashtop__stat" title="Estimated number of standard-length messages your balance can send">
          <IconMessage width={18} height={18} />
          <span className="dashtop__stat-value">{data ? number(data.sms_balance) : "—"}</span>
          <span className="dashtop__stat-label">SMS balance</span>
        </Link>
        <Link to="/dashboard/wallet" className="dashtop__stat">
          <IconWallet width={18} height={18} />
          <span className="dashtop__stat-value">{data ? ghs(data.balance_pesewas) : "—"}</span>
          <span className="dashtop__stat-label">Wallet</span>
        </Link>
      </div>

      <div className="dashtop__account">
        <div className="dashtop__who">
          <p className="dashtop__name">{user.full_name}</p>
          <p className="dashtop__org">{user.organization?.name}</p>
        </div>
        <button type="button" className="dashtop__logout" onClick={signOut}>
          <IconLogout width={18} height={18} /> <span>Log out</span>
        </button>
      </div>
    </header>
  );
}
