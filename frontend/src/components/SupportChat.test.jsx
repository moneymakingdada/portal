import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../lib/api";
import SupportChat from "./SupportChat";

vi.mock("../lib/api", async (orig) => ({ ...(await orig()), api: { get: vi.fn(), post: vi.fn() } }));

const reply = (over = {}) => ({ conversation_id: "c1", reply: "Top up on the Wallet page.", ticket_numbers: [], handoff_suggested: false, ...over });

function setup({ available = true, post } = {}) {
  api.get = vi.fn().mockResolvedValue({ assistant_available: available });
  api.post = post ?? vi.fn().mockResolvedValue(reply());
  render(<MemoryRouter><SupportChat /></MemoryRouter>);
}

const openChat = async (user) => user.click(await screen.findByRole("button", { name: /help/i }));
const input = () => screen.findByRole("textbox", { name: /your message/i });

beforeEach(() => vi.clearAllMocks());

describe("SupportChat", () => {
  it("starts closed, then opens with a greeting and checks the assistant is on", async () => {
    const user = userEvent.setup();
    setup();
    expect(screen.queryByRole("log")).toBeNull();
    await openChat(user);
    expect(await screen.findByText(/what do you need help with/i)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/support/chat");
  });

  it("sends a message, shows the reply, and keeps the same conversation for the next one", async () => {
    const user = userEvent.setup();
    setup();
    await openChat(user);
    await user.type(await input(), "how do I add money?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Top up on the Wallet page.")).toBeInTheDocument();
    expect(screen.getByText("how do I add money?")).toBeInTheDocument();
    expect(api.post).toHaveBeenLastCalledWith("/support/chat", { message: "how do I add money?" });

    await user.type(await input(), "and then?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    expect(api.post).toHaveBeenLastCalledWith("/support/chat", { message: "and then?", conversation_id: "c1" });
  });

  it("sends on Enter but not on Shift+Enter, and not when empty", async () => {
    const user = userEvent.setup();
    setup();
    await openChat(user);
    const box = await input();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.type(box, "   {Enter}");
    expect(api.post).not.toHaveBeenCalled();
    await user.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    expect(api.post).not.toHaveBeenCalled();
    await user.type(box, "{Enter}");
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1].message).toBe("line one\nline two");
  });

  it("can't send twice while it's waiting for a reply", async () => {
    const user = userEvent.setup();
    let finish;
    setup({ post: vi.fn(() => new Promise((r) => { finish = r; })) });
    await openChat(user);
    await user.type(await input(), "hello{Enter}");
    expect(await screen.findByText(/looking into it/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.type(await input(), "again{Enter}");
    expect(api.post).toHaveBeenCalledTimes(1);
    finish(reply());
    expect(await screen.findByText("Top up on the Wallet page.")).toBeInTheDocument();
  });

  it("gives the message back to be retried when sending fails", async () => {
    const user = userEvent.setup();
    setup({ post: vi.fn().mockRejectedValue(new ApiError({ status: 429, code: "rate_limited", message: "You've sent a lot of messages." })) });
    await openChat(user);
    await user.type(await input(), "please help");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You've sent a lot of messages.");
    expect(await input()).toHaveValue("please help");
    expect(screen.queryByText("please help", { selector: "p" })).toBeNull();
  });

  it("shows the reply as plain text, never as HTML", async () => {
    const user = userEvent.setup();
    const evil = '<img src=x onerror="alert(1)"> **bold**';
    setup({ post: vi.fn().mockResolvedValue(reply({ reply: evil })) });
    await openChat(user);
    await user.type(await input(), "hi{Enter}");
    expect(await screen.findByText(evil)).toBeInTheDocument();
    expect(document.querySelector(".chat__log img")).toBeNull();
  });

  it("offers the team form when the assistant says it can't help, and reports the ticket", async () => {
    const user = userEvent.setup();
    setup({ post: vi.fn().mockResolvedValue(reply({ reply: "I can't look into this right now.", handoff_suggested: true })) });
    api.post.mockImplementation((url) => url === "/support/tickets"
      ? Promise.resolve({ id: 42 }) : Promise.resolve(reply({ reply: "I can't look into this right now.", handoff_suggested: true })));
    await openChat(user);
    await user.type(await input(), "hi{Enter}");
    await user.type(await screen.findByLabelText("What's the problem?"), "No SMS");
    await user.type(screen.getByLabelText("Details"), "Nothing arrives");
    await user.click(screen.getByRole("button", { name: "Send to our team" }));
    expect(await screen.findByText(/ticket #42 opened/i)).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith("/support/tickets", { subject: "No SMS", details: "Nothing arrives" });
    expect(screen.queryByLabelText("What's the problem?")).toBeNull();
    expect(screen.getByRole("link", { name: /support page/i })).toHaveAttribute("href", "/dashboard/support");
  });

  it("tells the customer when the assistant opened a ticket for them", async () => {
    const user = userEvent.setup();
    setup({ post: vi.fn().mockResolvedValue(reply({ ticket_numbers: [7] })) });
    await openChat(user);
    await user.type(await input(), "I paid and got nothing{Enter}");
    expect(await screen.findByText(/ticket #7 opened/i)).toBeInTheDocument();
  });

  it("goes straight to the team form, with no chat box, when the assistant is off", async () => {
    const user = userEvent.setup();
    setup({ available: false });
    await openChat(user);
    expect(await screen.findByLabelText("What's the problem?")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /your message/i })).toBeNull();
  });

  it("lets someone ask for a person at any time", async () => {
    const user = userEvent.setup();
    setup();
    await openChat(user);
    await user.click(await screen.findByRole("button", { name: /talk to a person/i }));
    expect(await screen.findByLabelText("What's the problem?")).toBeInTheDocument();
  });

  it("starts fresh on New chat, without the old conversation id", async () => {
    const user = userEvent.setup();
    setup();
    await openChat(user);
    await user.type(await input(), "one{Enter}");
    await screen.findByText("Top up on the Wallet page.");
    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.queryByText("one")).toBeNull();
    await user.type(await input(), "two{Enter}");
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    expect(api.post).toHaveBeenLastCalledWith("/support/chat", { message: "two" });
  });

  it("stops accepting messages when a chat is full and offers a new one", async () => {
    const user = userEvent.setup();
    setup({ post: vi.fn().mockRejectedValue(new ApiError({ status: 409, code: "conversation_full", message: "This chat is full." })) });
    await openChat(user);
    await user.type(await input(), "hi{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("This chat is full.");
    expect(await input()).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /start a new chat/i }));
    expect(await input()).toBeEnabled();
  });

  it("closes with the button and with Escape", async () => {
    const user = userEvent.setup();
    setup();
    await openChat(user);
    await user.click(screen.getByRole("button", { name: /close support chat/i }));
    expect(screen.queryByRole("log")).toBeNull();
    await openChat(user);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("log")).toBeNull();
  });
});
