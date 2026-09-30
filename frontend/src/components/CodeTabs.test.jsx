import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CodeTabs from "./CodeTabs";

const SAMPLES = [
  { id: "curl", label: "curl", code: "curl http://example.com" },
  { id: "js", label: "JavaScript", code: "fetch('http://example.com')" },
];

function stubClipboard() {
  // user-event's setup() may already have installed a clipboard stub (for
  // paste support) with a non-configurable property, so patch its method
  // instead of redefining the property when one is already there.
  if (navigator.clipboard?.writeText) {
    return vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
  }
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

let writeText;
beforeEach(() => {
  writeText = stubClipboard();
});

describe("CodeTabs", () => {
  it("shows the first sample by default", () => {
    render(<CodeTabs samples={SAMPLES} />);
    expect(screen.getByRole("tabpanel")).toHaveTextContent("curl http://example.com");
  });

  it("switches panes when a tab is clicked", async () => {
    const user = userEvent.setup();
    render(<CodeTabs samples={SAMPLES} />);
    await user.click(screen.getByRole("tab", { name: "JavaScript" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("fetch");
  });

  it("copies the currently active sample's code", async () => {
    const user = userEvent.setup();
    render(<CodeTabs samples={SAMPLES} />);
    await user.click(screen.getByRole("tab", { name: "JavaScript" }));
    await user.click(screen.getByRole("button", { name: /copy/i }));
    expect(writeText).toHaveBeenCalledWith("fetch('http://example.com')");
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("moves between tabs with arrow keys", async () => {
    const user = userEvent.setup();
    render(<CodeTabs samples={SAMPLES} />);
    const tabs = within(screen.getByRole("tablist"));
    tabs.getByRole("tab", { name: "curl" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(tabs.getByRole("tab", { name: "JavaScript" })).toHaveFocus();
    expect(tabs.getByRole("tab", { name: "JavaScript" })).toHaveAttribute("aria-selected", "true");
  });
});
