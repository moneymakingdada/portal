import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { LEGAL_UPDATED, LEGAL_VERSION } from "../../lib/legal";
import Privacy from "./Privacy";
import Terms from "./Terms";

const show = (page) => render(<MemoryRouter>{page}</MemoryRouter>);

describe("legal pages", () => {
  it.each([
    ["Terms of Service", <Terms />],
    ["Privacy Policy", <Privacy />],
  ])("%s has a title, a date, a short summary and a working contents list", (title, page) => {
    show(page);
    expect(screen.getByRole("heading", { level: 1, name: title })).toBeInTheDocument();
    expect(screen.getByText(`Last updated ${LEGAL_UPDATED}`)).toBeInTheDocument();
    expect(screen.getByText(/in short/i)).toBeInTheDocument();

    const toc = screen.getByRole("navigation", { name: "Contents" });
    const links = within(toc).getAllByRole("link");
    expect(links.length).toBeGreaterThan(8);
    for (const link of links) {
      const target = document.getElementById(link.getAttribute("href").slice(1));
      expect(target, link.textContent).not.toBeNull();
    }
    expect(document.title).toContain(title);
  });

  it("the version people accept matches the date shown on the pages", () => {
    expect(LEGAL_VERSION).toBe("2026-10-24");
    expect(LEGAL_UPDATED).toBe("24 October 2026");
  });

  it("each page links to the other and back home", () => {
    show(<Terms />);
    expect(screen.getAllByRole("link", { name: "Privacy Policy" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
  });

  it("never shows contact details that haven't been configured", () => {
    show(<Privacy />);
    expect(screen.queryByText(/example\.com/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/support contact shown on our website/i).length).toBeGreaterThan(0);
  });

  it("explains the Ghana data protection rights and who the processor is", () => {
    show(<Privacy />);
    expect(screen.getAllByText(/Data Protection Act, 2012/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Data Protection Commission of Ghana/)).toBeInTheDocument();
    expect(screen.getByText(/data processor/i)).toBeInTheDocument();
  });
});
