import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OtpInput from "./OtpInput";

function setup(props = {}) {
  const onChange = vi.fn();
  const onComplete = vi.fn();
  const utils = render(<OtpInput length={6} value="" onChange={onChange} onComplete={onComplete} {...props} />);
  return { onChange, onComplete, ...utils };
}

describe("OtpInput", () => {
  it("renders one box per digit", () => {
    setup();
    expect(screen.getAllByRole("textbox")).toHaveLength(6);
  });

  it("typing one digit advances focus and reports the value", async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    const boxes = screen.getAllByRole("textbox");
    await user.type(boxes[0], "4");
    expect(onChange).toHaveBeenCalledWith("4");
  });

  it("calls onComplete once all boxes are filled", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    function Controlled() {
      const [value, setValue] = useState("");
      return <OtpInput length={6} value={value} onChange={setValue} onComplete={onComplete} />;
    }
    render(<Controlled />);
    const boxes = screen.getAllByRole("textbox");
    for (const box of boxes) await user.type(box, "1");
    expect(onComplete).toHaveBeenCalledWith("111111");
  });

  it("pasting a full code fills every box and completes", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    function Controlled() {
      const [value, setValue] = useState("");
      return <OtpInput length={6} value={value} onChange={setValue} onComplete={onComplete} />;
    }
    render(<Controlled />);
    const boxes = screen.getAllByRole("textbox");
    boxes[0].focus();
    await user.paste("482917");
    expect(onComplete).toHaveBeenCalledWith("482917");
  });

  it("Backspace on an empty box moves focus back and clears the previous digit", async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [value, setValue] = useState("12");
      return <OtpInput length={6} value={value} onChange={setValue} />;
    }
    render(<Controlled />);
    const boxes = screen.getAllByRole("textbox");
    boxes[2].focus();
    await user.keyboard("{Backspace}");
    // The box that held the removed digit is now empty and keeps focus, ready to retype.
    expect(boxes[1]).toHaveValue("");
    expect(document.activeElement).toBe(boxes[1]);
  });

  it("marks boxes invalid via aria-invalid", () => {
    setup({ invalid: true });
    for (const box of screen.getAllByRole("textbox")) expect(box).toHaveAttribute("aria-invalid", "true");
  });

  it("disables every box when disabled", () => {
    setup({ disabled: true });
    for (const box of screen.getAllByRole("textbox")) expect(box).toBeDisabled();
  });
});
