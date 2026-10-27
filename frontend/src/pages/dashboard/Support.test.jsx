import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import Support from "./Support";

vi.mock("../../lib/api", async (orig) => ({ ...(await orig()), api: { get: vi.fn(), post: vi.fn() } }));

const TICKETS = [
  { id: 2, subject: "Paid, no credit", details: "Ref abc", status: "answered", staff_reply: "Credited, sorry!", replied_at: "2026-10-27T10:00:00Z", created_at: "2026-10-27T09:00:00Z" },
  { id: 1, subject: "Sender ID", details: "Still pending", status: "open", staff_reply: null, replied_at: null, created_at: "2026-10-26T09:00:00Z" },
];

const renderPage = () => render(<MemoryRouter><Support /></MemoryRouter>);
beforeEach(() => vi.clearAllMocks());

describe("Support page", () => {
  it("lists tickets with their status and any staff reply", async () => {
    api.get = vi.fn().mockResolvedValue({ results: TICKETS });
    renderPage();
    expect(await screen.findByText("#2 Paid, no credit")).toBeInTheDocument();
    expect(screen.getByText("Credited, sorry!")).toBeInTheDocument();
    expect(screen.getByText("Answered")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getAllByText(/our reply/i)).toHaveLength(1);
  });

  it("says so when there are no tickets", async () => {
    api.get = vi.fn().mockResolvedValue({ results: [] });
    renderPage();
    expect(await screen.findByText("No tickets yet")).toBeInTheDocument();
  });

  it("shows an error with a retry when the list can't load", async () => {
    api.get = vi.fn().mockRejectedValueOnce(new Error("boom")).mockResolvedValue({ results: [] });
    renderPage();
    const retry = await screen.findByRole("button", { name: /try again/i });
    await userEvent.click(retry);
    expect(await screen.findByText("No tickets yet")).toBeInTheDocument();
  });

  it("sends a ticket, clears the form and refreshes the list", async () => {
    const user = userEvent.setup();
    api.get = vi.fn().mockResolvedValue({ results: [] });
    api.post = vi.fn().mockResolvedValue({ id: 3 });
    renderPage();
    await screen.findByText("No tickets yet");
    const send = screen.getByRole("button", { name: "Send to our team" });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText("What's the problem?"), "  Help  ");
    await user.type(screen.getByLabelText("Details"), "It broke");
    await user.click(send);
    expect(api.post).toHaveBeenCalledWith("/support/tickets", { subject: "Help", details: "It broke" });
    await vi.waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("What's the problem?")).toHaveValue("");
  });

  it("shows the server's message when sending fails and keeps what was typed", async () => {
    const user = userEvent.setup();
    api.get = vi.fn().mockResolvedValue({ results: [] });
    api.post = vi.fn().mockRejectedValue(Object.assign(new Error("You've sent a lot of tickets today."), { code: "tickets_rate_limited" }));
    renderPage();
    await screen.findByText("No tickets yet");
    await user.type(screen.getByLabelText("What's the problem?"), "Help");
    await user.type(screen.getByLabelText("Details"), "It broke");
    await user.click(screen.getByRole("button", { name: "Send to our team" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You've sent a lot of tickets today.");
    expect(screen.getByLabelText("Details")).toHaveValue("It broke");
  });
});
