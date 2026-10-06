import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./lib/auth";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import DashboardLayout from "./pages/dashboard/DashboardLayout";
import Overview from "./pages/dashboard/Overview";
import ApiKeys from "./pages/dashboard/ApiKeys";
import SenderIds from "./pages/dashboard/SenderIds";
import Customers from "./pages/dashboard/Customers";
import CustomerDetail from "./pages/dashboard/CustomerDetail";
import Templates from "./pages/dashboard/Templates";
import Messages from "./pages/dashboard/Messages";
import Wallet from "./pages/dashboard/Wallet";
import Plans from "./pages/dashboard/Plans";
import Quickstart from "./pages/dashboard/Quickstart";
import { Loading } from "./components/ui";

function FullPageLoading() {
  return <div className="fullpage"><Loading label="Loading…" /></div>;
}

/** Only signed-in users. Anyone else goes to /login and comes back here afterwards. */
export function ProtectedRoute({ children }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <FullPageLoading />;
  if (status === "anon") return <Navigate to="/login" replace state={{ from: location }} />;
  return children;
}

/** Login and sign-up are pointless for someone already signed in. */
function PublicOnly({ children }) {
  const { status } = useAuth();
  if (status === "loading") return <FullPageLoading />;
  if (status === "authed") return <Navigate to="/dashboard" replace />;
  return children;
}

function NotFound() {
  return (
    <div className="fullpage">
      <div>
        <h1 className="notfound__title">Page not found</h1>
        <p className="notfound__text">That address doesn't lead anywhere.</p>
        <Link to="/" className="btn btn--forest">Back to the home page</Link>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
      <Route path="/signup" element={<PublicOnly><Signup /></PublicOnly>} />
      <Route path="/dashboard" element={<ProtectedRoute><DashboardLayout /></ProtectedRoute>}>
        <Route index element={<Overview />} />
        <Route path="customers" element={<Customers />} />
        <Route path="customers/:id" element={<CustomerDetail />} />
        <Route path="templates" element={<Templates />} />
        <Route path="api-keys" element={<ApiKeys />} />
        <Route path="sender-ids" element={<SenderIds />} />
        <Route path="messages" element={<Messages />} />
        <Route path="wallet" element={<Wallet />} />
        <Route path="plans" element={<Plans />} />
        <Route path="quickstart" element={<Quickstart />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
