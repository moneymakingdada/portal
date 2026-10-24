import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../lib/api";
import { LEGAL_VERSION } from "../lib/legal";
import Signup from "./Signup";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal()),
  api: { post: vi.fn() },
}));
vi.mock("../lib/auth", () => ({ useAuth: () => ({ signIn: vi.fn() }) }));

const STARTED = { signup_id: "abc", phone_masked: "+233 *** *** 567", code_length: 6, expires_in: 600, resend_in: 60 };

async function fillIn(user) {
  await user.type(screen.getByLabelText("Your name"), "Ama Mensah");
  await user.type(screen.getByLabelText("Business or app name"), "Adom Bakery");
  await user.type(screen.getByLabelText("Email"), "ama@example.com");
  await user.type(screen.getByLabelText("Mobile number"), "0241234567");
  await user.type(screen.getByLabelText("Password"), "Correct-horse-9");
}

describe("Signup terms", () => {
  beforeEach(() => {
    sessionStorage.clear();
    api.post = vi.fn().mockResolvedValue(STARTED);
    render(<MemoryRouter><Signup /></MemoryRouter>);
  });

  it("links to the terms and privacy pages, opening them in a new tab so the form isn't lost", () => {
    const terms = screen.getByRole("link", { name: "Terms of Service" });
    const privacy = screen.getByRole("link", { name: "Privacy Policy" });
    expect(terms).toHaveAttribute("href", "/terms");
    expect(privacy).toHaveAttribute("href", "/privacy");
    for (const link of [terms, privacy]) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel")).toContain("noopener");
    }
  });

  it("starts unticked, and explains what to do instead of silently doing nothing", async () => {
    const user = userEvent.setup();
    const box = screen.getByRole("checkbox", { name: /i agree to the terms of service/i });
    expect(box).not.toBeChecked();
    await fillIn(user);
    await user.click(screen.getByRole("button", { name: /send verification code/i }));

    expect(await screen.findByText(/tick the box to agree/i)).toBeInTheDocument();
    expect(box).toHaveAttribute("aria-invalid", "true");
    expect(box).toHaveFocus();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("clears the reminder once the box is ticked, then signs up with the version it showed", async () => {
    const user = userEvent.setup();
    await fillIn(user);
    await user.click(screen.getByRole("button", { name: /send verification code/i }));
    await user.click(screen.getByRole("checkbox", { name: /i agree/i }));
    expect(screen.queryByText(/tick the box to agree/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /send verification code/i }));
    expect(await screen.findByText(/we sent a 6-digit code/i)).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith("/auth/signup", expect.objectContaining({
      email: "ama@example.com", accept_terms: true, terms_version: LEGAL_VERSION,
    }));
  });

  it("asks for a refresh if the terms changed while the form was open", async () => {
    api.post = vi.fn().mockRejectedValue(new ApiError({ status: 409, code: "terms_outdated", message: "Our terms were just updated. Refresh the page to read and accept them." }));
    const user = userEvent.setup();
    await fillIn(user);
    await user.click(screen.getByRole("checkbox", { name: /i agree/i }));
    await user.click(screen.getByRole("button", { name: /send verification code/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/refresh the page/i);
  });

  it("shows the server's message if it still refuses the missing agreement", async () => {
    api.post = vi.fn().mockRejectedValue(new ApiError({ status: 400, code: "validation_error", fields: { accept_terms: ["Tick the box to agree to the Terms of Service and Privacy Policy."] } }));
    const user = userEvent.setup();
    await fillIn(user);
    await user.click(screen.getByRole("checkbox", { name: /i agree/i }));
    await user.click(screen.getByRole("button", { name: /send verification code/i }));
    expect(await screen.findByText(/tick the box to agree/i)).toBeInTheDocument();
  });
});
