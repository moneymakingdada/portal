import { useRef } from "react";

/**
 * One box per digit. Handles typing, pasting a whole code, Backspace, arrow keys
 * and one-time-code autofill (SMS suggestions on phones put the full code in the
 * first box). `value` is always a contiguous string of digits.
 */
export default function OtpInput({
  length = 6, value, onChange, onComplete, disabled = false, invalid = false,
  label = "Verification code", autoFocus = false,
}) {
  const refs = useRef([]);
  const digits = Array.from({ length }, (_, i) => value[i] ?? "");

  const focus = (i) => refs.current[Math.max(0, Math.min(i, length - 1))]?.focus();

  const update = (next, focusIndex) => {
    onChange(next);
    if (focusIndex != null) focus(focusIndex);
    if (next.length === length) onComplete?.(next);
  };

  const handleChange = (i, event) => {
    const typed = event.target.value.replace(/\D/g, "");
    if (!typed) {
      update(value.slice(0, i) + value.slice(i + 1));
      return;
    }
    if (typed.length === 1) {
      update((value.slice(0, i) + typed + value.slice(i + 1)).slice(0, length), i + 1);
    } else {
      // Autofill or a multi-digit insert: spread from this box onward.
      const next = (value.slice(0, i) + typed).slice(0, length);
      update(next, next.length);
    }
  };

  const handleKeyDown = (i, event) => {
    if (event.key === "Backspace" && !digits[i] && i > 0) {
      event.preventDefault();
      update(value.slice(0, i - 1) + value.slice(i), i - 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      focus(i - 1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      focus(i + 1);
    }
  };

  const handlePaste = (event) => {
    const pasted = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, length);
    if (!pasted) return;
    event.preventDefault();
    update(pasted, pasted.length);
  };

  const handleFocus = (i, event) => {
    if (i > value.length) {           // keep the digits contiguous: jump to the first empty box
      focus(value.length);
      return;
    }
    event.target.select();
  };

  return (
    <div className="otp" role="group" aria-label={label}>
      {digits.map((digit, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el; }}
          className={`otp__box${invalid ? " otp__box--invalid" : ""}`}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          maxLength={length}
          value={digit}
          disabled={disabled}
          autoFocus={autoFocus && i === 0}
          aria-label={`Digit ${i + 1} of ${length}`}
          aria-invalid={invalid || undefined}
          onChange={(e) => handleChange(i, e)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onPaste={handlePaste}
          onFocus={(e) => handleFocus(i, e)}
        />
      ))}
    </div>
  );
}
