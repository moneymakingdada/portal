import { useEffect, useId, useRef, useState } from "react";
import { copyText } from "../lib/format";
import { IconCheck, IconCopy } from "./icons";

export default function CodeTabs({ samples, label = "Code samples" }) {
  const uid = useId();
  const [active, setActive] = useState(samples[0].id);
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  const tabRefs = useRef({});
  const current = samples.find((s) => s.id === active) ?? samples[0];

  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    if (await copyText(current.code)) {
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1800);
    }
  };

  const onKeyDown = (event) => {
    const index = samples.findIndex((s) => s.id === active);
    let next = null;
    if (event.key === "ArrowRight") next = (index + 1) % samples.length;
    if (event.key === "ArrowLeft") next = (index - 1 + samples.length) % samples.length;
    if (next === null) return;
    event.preventDefault();
    const id = samples[next].id;
    setActive(id);
    tabRefs.current[id]?.focus();
  };

  return (
    <div className="codetabs">
      <div className="codetabs__bar">
        <div role="tablist" aria-label={label} className="codetabs__tabs" onKeyDown={onKeyDown}>
          {samples.map((s) => (
            <button
              key={s.id}
              ref={(el) => { tabRefs.current[s.id] = el; }}
              type="button"
              role="tab"
              id={`${uid}-tab-${s.id}`}
              aria-selected={s.id === active}
              aria-controls={`${uid}-panel`}
              tabIndex={s.id === active ? 0 : -1}
              className="codetabs__tab"
              onClick={() => setActive(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <button type="button" className="codetabs__copy" onClick={copy}>
          {copied ? <IconCheck width={16} height={16} /> : <IconCopy width={16} height={16} />}
          <span aria-live="polite">{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      <pre className="codetabs__pane" role="tabpanel" id={`${uid}-panel`} aria-labelledby={`${uid}-tab-${active}`} tabIndex={0}>
        <code>{current.code}</code>
      </pre>
    </div>
  );
}
