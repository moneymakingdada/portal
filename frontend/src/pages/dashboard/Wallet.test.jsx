import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import Wallet from "./Wallet";

vi.mock("../../lib/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock("../../lib/navigate", () => ({ redirectTo: vi.fn() }));

const WALLET = { balance_pesewas: 10000, currency: "GHS", sms_balance: 2000 };
const LEDGER = { count: 0, page: 1, page_size: 20, total_pages: 1, results: [] };

/** Configure api.get for a test. `verify` answers /wallet/topup/verify calls:
 *  a value (resolved once) or a function (called per request, for call-count checks). */
function mockGet({ verify } = {}) {
  api.get = vi.fn((url) => {
    if (url.startsWith("/wallet/topup/verify")) {
      if (verify === undefined) return Promise.reject(new Error(`unexpected verify call: ${url}`));
      return typeof verify === "function" ? verify(url) : Promise.resolve(verify);
    }
    if (url.startsWith("/wallet/ledger")) return Promise.resolve(LEDGER);
    if (url === "/wallet") return Promise.resolve(WALLET);
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Wallet />
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.restoreAllMocks());

describe("Wallet: normal load", () => {
  it("shows the balance with no payment banner when there's no reference", async () => {
    mockGet();
    renderAt("/dashboard/wallet");
    expect(await screen.findByText("GH₵100.00")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("Wallet: returning from Paystack", () => {
  it("shows success and refreshes the balance", async () => {
    mockGet({ verify: { status: "success", amount_pesewas: 5000, plan_name: null,
                        balance_pesewas: 15000, sms_balance: 3000 } });
    renderAt("/dashboard/wallet?reference=portal_abc123");

    expect(await screen.findByText(/Payment received/)).toBeInTheDocument();
    expect(screen.getByText(/GH₵50\.00/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/wallet/topup/verify?reference=portal_abc123");
  });

  it("checks the reference exactly once, even if the component re-renders", async () => {
    let calls = 0;
    mockGet({ verify: () => { calls += 1; return Promise.resolve({ status: "success", amount_pesewas: 5000, balance_pesewas: 15000, sms_balance: 3000 }); } });
    const { rerender } = renderAt("/dashboard/wallet?reference=portal_abc123");
    await screen.findByText(/Payment received/);

    rerender(
      <MemoryRouter initialEntries={["/dashboard/wallet?reference=portal_abc123"]}>
        <Wallet />
      </MemoryRouter>,
    );
    await waitFor(() => expect(calls).toBe(1));
  });

  it("shows a pending message with a retry button, and retry re-checks", async () => {
    const user = userEvent.setup();
    let call = 0;
    mockGet({
      verify: () => {
        call += 1;
        return Promise.resolve(call === 1
          ? { status: "pending" }
          : { status: "success", amount_pesewas: 5000, balance_pesewas: 15000, sms_balance: 3000 });
      },
    });
    renderAt("/dashboard/wallet?reference=portal_pending");

    expect(await screen.findByText(/haven't had confirmation/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /check again/i }));
    expect(await screen.findByText(/Payment received/)).toBeInTheDocument();
    expect(call).toBe(2);
  });

  it("shows a failure message naming the reference, with no retry button", async () => {
    mockGet({ verify: { status: "failed" } });
    renderAt("/dashboard/wallet?reference=portal_bad");

    expect(await screen.findByText(/wasn't completed/)).toBeInTheDocument();
    expect(screen.getByText(/portal_bad/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /check again/i })).not.toBeInTheDocument();
  });

  it("a network error while checking offers retry too", async () => {
    mockGet({ verify: () => Promise.reject(new Error("Can't reach the server.")) });
    renderAt("/dashboard/wallet?reference=portal_neterr");
    expect(await screen.findByText("Can't reach the server.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /check again/i })).toBeInTheDocument();
  });
});
