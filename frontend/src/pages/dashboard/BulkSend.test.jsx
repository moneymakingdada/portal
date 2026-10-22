import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../../lib/api";
import BulkSend from "./BulkSend";

vi.mock("../../lib/api", async (importOriginal) => ({
  ...(await importOriginal()),
  api: { get: vi.fn(), post: vi.fn() },
}));

const TEMPLATES = { results: [
  { id: "t1", category: "thank_you", body: "Thank you {first_name}, from {business_name}!" },
  { id: "t2", category: "welcome", body: "Welcome {first_name}." },
] };
const SENDERS = { results: [
  { id: 1, name: "Acme", status: "approved" },
  { id: 2, name: "Pending", status: "pending" },
] };

const REVIEW = {
  dry_run: true,
  summary: { found: 6, valid: 4, duplicates: 1, invalid: 1, opted_out: 1, to_send: 3, sms_parts: 3,
    cost_pesewas: 15, balance_pesewas: 500, enough_funds: true, shortfall_pesewas: 0,
    daily_cap_room_pesewas: 50000, within_daily_cap: 3 },
  invalid: [{ value: "12345", reason: "Not a valid Ghana mobile number.", where: "line 2" }],
  warnings: {},
  sample: { to: "+233241234567", body: "Thank you there, from Acme Ltd!" },
};

const campaign = (over = {}) => ({
  id: "c1", status: "done", category: "thank_you", body: "Thank you", total: 3, accepted: 3, skipped: 0, failed: 0,
  skipped_reasons: {}, delivered: 3, sent: 0, in_queue: 0, delivery_failed: 0, cost_pesewas: 15,
  created_at: "2026-10-22T09:00:00Z", finished_at: "2026-10-22T09:00:05Z", ...over,
});

function renderPage() {
  return render(<MemoryRouter><BulkSend /></MemoryRouter>);
}

const form = (callIndex = 0) => api.post.mock.calls[callIndex][1];

async function pasteNumbers(user, text = "0241234567, 0551234567") {
  await user.click(screen.getByLabelText("Paste phone numbers"));
  await user.paste(text);
}

describe("BulkSend", () => {
  beforeEach(() => {
    api.get = vi.fn((path) => {
      if (path === "/templates") return Promise.resolve(TEMPLATES);
      if (path === "/sender-ids") return Promise.resolve(SENDERS);
      if (path === "/bulk") return Promise.resolve({ results: [] });
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });
    api.post = vi.fn();
  });
  afterEach(() => vi.useRealTimers());

  it("starts from your saved template and can't be reviewed until there are numbers", async () => {
    const user = userEvent.setup();
    renderPage();
    const message = await screen.findByLabelText("Message");
    await waitFor(() => expect(message).toHaveValue(TEMPLATES.results[0].body));
    const review = screen.getByRole("button", { name: /review before sending/i });
    expect(review).toBeDisabled();
    await pasteNumbers(user);
    expect(review).toBeEnabled();
  });

  it("explains which separators work and links to the sample file", async () => {
    renderPage();
    expect(await screen.findByText(/comma, colon, pipe/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download a sample file/i })).toHaveAttribute("href", "/api/bulk/sample");
  });

  it("reviews first: sends nothing, and shows the plan, cost and a sample", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue(REVIEW);
    renderPage();
    await screen.findByText("Welcome");
    await pasteNumbers(user, "0241234567");
    await user.click(screen.getByRole("button", { name: /review before sending/i }));

    expect(await screen.findByText("3 people will get this message")).toBeInTheDocument();
    expect(form().get("dry_run")).toBe("true");
    expect(form().get("numbers")).toBe("0241234567");
    expect(form().get("category")).toBe("thank_you");
    expect(form().has("message")).toBe(false);               // unedited: the server uses the template
    expect(form().has("client_token")).toBe(false);
    expect(screen.getByText("Thank you there, from Acme Ltd!")).toBeInTheDocument();
    expect(screen.getByText(/Duplicates removed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send to 3 people/i })).toBeEnabled();
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it("lists the numbers that were left out and why", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue(REVIEW);
    renderPage();
    await pasteNumbers(user);
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    await user.click(await screen.findByText(/that was left out/i));
    expect(screen.getByText("12345")).toBeInTheDocument();
    expect(screen.getByText(/line 2: Not a valid Ghana mobile number/)).toBeInTheDocument();
  });

  it("blocks sending, and points to Buy SMS, when the wallet can't cover it", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue({ ...REVIEW, summary: { ...REVIEW.summary, enough_funds: false, shortfall_pesewas: 250 } });
    renderPage();
    await pasteNumbers(user);
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    expect(await screen.findByText(/You need/)).toHaveTextContent("GH₵2.50");
    expect(screen.getByRole("link", { name: /buy sms/i })).toHaveAttribute("href", "/dashboard/plans");
    expect(screen.getByRole("button", { name: /send to 3 people/i })).toBeDisabled();
  });

  it("warns when the daily limit only covers part of the list", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue({ ...REVIEW, summary: { ...REVIEW.summary, within_daily_cap: 1 } });
    renderPage();
    await pasteNumbers(user);
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    expect(await screen.findByText(/room for 1 of these today/)).toBeInTheDocument();
  });

  it("sends with a token after review, then clears the list and reports the result", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValueOnce(REVIEW).mockResolvedValueOnce(campaign());
    renderPage();
    await pasteNumbers(user);
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    await user.click(await screen.findByRole("button", { name: /send to 3 people/i }));

    expect(await screen.findByText("Done.")).toBeInTheDocument();
    expect(form(1).get("dry_run")).toBe("false");
    expect(form(1).get("client_token")).toMatch(/.{8,}/);
    expect(form(1).get("save_customers")).toBe("true");
    expect(screen.getByText(/3 delivered/)).toBeInTheDocument();
    expect(screen.getByLabelText("Paste phone numbers")).toHaveValue("");
    expect(screen.queryByRole("button", { name: /send to/i })).not.toBeInTheDocument();
  });

  it("retrying a send that failed in transit reuses the same token, so it can't send twice", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValueOnce(REVIEW)
      .mockRejectedValueOnce(new ApiError({ status: 0, code: "network_error", message: "Can't reach the server." }))
      .mockResolvedValueOnce(campaign());
    renderPage();
    await pasteNumbers(user);
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    await user.click(await screen.findByRole("button", { name: /send to 3 people/i }));
    expect(await screen.findByText("Can't reach the server.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /send to 3 people/i }));
    await screen.findByText("Done.");
    expect(form(2).get("client_token")).toBe(form(1).get("client_token"));
  });

  it("any change after reviewing hides the review, so you can't send what you didn't check", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue(REVIEW);
    renderPage();
    await pasteNumbers(user);
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    await screen.findByText("3 people will get this message");
    await user.type(screen.getByLabelText("Paste phone numbers"), ", 0201112222");
    expect(screen.queryByText("3 people will get this message")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send to/i })).not.toBeInTheDocument();
  });

  it("an edited message is sent as your own text; an approved sender can be chosen", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue(REVIEW);
    renderPage();
    await screen.findByText("Acme");
    const options = within(screen.getByLabelText("Send as")).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Default sender", "Acme"]);        // pending ones aren't offered
    await user.selectOptions(screen.getByLabelText("Send as"), "Acme");
    const message = screen.getByLabelText("Message");
    await user.clear(message);
    await user.type(message, "Hello everyone");
    await pasteNumbers(user);
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    await screen.findByText("3 people will get this message");
    expect(form().get("message")).toBe("Hello everyone");
    expect(form().get("sender_id")).toBe("Acme");
  });

  it("can opt out of saving contacts", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue(REVIEW);
    renderPage();
    await pasteNumbers(user);
    await user.click(screen.getByRole("checkbox", { name: /save these people to my customers/i }));
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    await screen.findByText("3 people will get this message");
    expect(form().get("save_customers")).toBe("false");
  });

  it("uploads a chosen file with the review request and rejects oversized files up front", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue(REVIEW);
    renderPage();
    const input = await screen.findByLabelText("Or upload a file");
    const big = new File(["x"], "big.csv", { type: "text/csv" });
    Object.defineProperty(big, "size", { value: 3 * 1024 * 1024 });
    await user.upload(input, big);
    expect(screen.getByText(/under 2 MB/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /review before sending/i })).toBeDisabled();

    await user.upload(input, new File(["Phone Number\n0241234567"], "contacts.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    await screen.findByText("3 people will get this message");
    expect(form().get("file").name).toBe("contacts.csv");
  });

  it("shows the server's reason when a list can't be used", async () => {
    const user = userEvent.setup();
    api.post.mockRejectedValue(new ApiError({ status: 400, code: "too_many_recipients", message: "That's 2,500 numbers. You can send to up to 2,000 at a time." }));
    renderPage();
    await pasteNumbers(user);
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("up to 2,000 at a time");
  });

  it("follows a running batch until it finishes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    api.post.mockResolvedValueOnce(REVIEW).mockResolvedValueOnce(campaign({ status: "running", accepted: 1, delivered: 0 }));
    const base = api.get.getMockImplementation();
    api.get = vi.fn((path) => (path === "/bulk/c1" ? Promise.resolve(campaign()) : base(path)));
    renderPage();
    await pasteNumbers(user);
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    await user.click(await screen.findByRole("button", { name: /send to 3 people/i }));
    expect(await screen.findByText(/1 of 3 processed/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /bulk send progress/i })).toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(2100); });
    expect(await screen.findByText("Done.")).toBeInTheDocument();
  });

  it("says plainly when a batch could not be started", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValueOnce(REVIEW).mockResolvedValueOnce(campaign({ status: "failed", accepted: 0, delivered: 0 }));
    renderPage();
    await pasteNumbers(user);
    await user.click(screen.getByRole("button", { name: /review before sending/i }));
    await user.click(await screen.findByRole("button", { name: /send to 3 people/i }));
    expect(await screen.findByText(/you weren't charged/i)).toBeInTheDocument();
  });

  it("lists recent bulk sends with their counts", async () => {
    const base = api.get.getMockImplementation();
    api.get = vi.fn((path) => (path === "/bulk"
      ? Promise.resolve({ results: [campaign({ body: "Happy holidays", total: 40, accepted: 38, skipped: 2, delivered: 35 })] })
      : base(path)));
    renderPage();
    const row = (await screen.findByText("Happy holidays")).closest("tr");
    expect(within(row).getByText("40")).toBeInTheDocument();
    expect(within(row).getByText("38")).toBeInTheDocument();
    expect(within(row).getByText("35")).toBeInTheDocument();
    expect(within(row).getByText("Done")).toBeInTheDocument();
  });
});
