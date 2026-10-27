import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { IconClose, IconSupport } from "./icons";
import TicketForm from "./TicketForm";
import "../styles/support.css";

const MAX_CHARS = 1000;
const GREETING = "Hi! I can look at your wallet, messages, sender IDs and payments and tell you what's going on. What do you need help with?";

/** Floating help chat. Every reply is shown as plain text: the model's words are never treated as HTML. */
export default function SupportChat() {
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState(null);       // null = not asked yet
  const [messages, setMessages] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [opened, setOpened] = useState([]);               // ticket numbers raised in this chat
  const logRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open || available !== null) return;
    let alive = true;
    api.get("/support/chat").then(
      (r) => alive && setAvailable(Boolean(r?.assistant_available)),
      () => alive && setAvailable(true),                  // can't tell: let them try, a real error will show
    );
    return () => { alive = false; };
  }, [open, available]);

  useEffect(() => {
    if (open && available) inputRef.current?.focus?.();
  }, [open, available]);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, busy, showForm, opened]);

  async function send() {
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    setError(null);
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text: message }]);
    try {
      const res = await api.post("/support/chat", { message, ...(conversationId ? { conversation_id: conversationId } : {}) });
      setConversationId(res.conversation_id);
      setMessages((m) => [...m, { role: "assistant", text: res.reply }]);
      if (res.ticket_numbers?.length) setOpened((n) => [...new Set([...n, ...res.ticket_numbers])]);
      if (res.handoff_suggested) setShowForm(true);
    } catch (err) {
      setMessages((m) => m.slice(0, -1));                 // take the unsent message back out ...
      setText(message);                                   // ... and give it back to the person to retry
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  function newChat() {
    setMessages([]);
    setConversationId(null);
    setError(null);
    setShowForm(false);
    setOpened([]);
  }

  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent?.isComposing) {
      event.preventDefault();
      send();
    }
  }

  function close() {
    setOpen(false);
  }

  if (!open) {
    return (
      <button type="button" className="chat__launcher" onClick={() => setOpen(true)}>
        <IconSupport /> Help
      </button>
    );
  }

  const full = error?.code === "conversation_full";
  return (
    <section className="chat" aria-label="Support chat" onKeyDown={(e) => e.key === "Escape" && close()}>
      <header className="chat__head">
        <h2 className="chat__title">Support</h2>
        <div className="chat__actions">
          {messages.length > 0 && <button type="button" className="btn btn--link" onClick={newChat}>New chat</button>}
          <button type="button" className="chat__close" onClick={close} aria-label="Close support chat"><IconClose /></button>
        </div>
      </header>

      {available === null ? (
        <p className="chat__body state" role="status">Loading…</p>
      ) : (
        <>
          <div className="chat__log" ref={logRef} role="log" aria-live="polite" aria-label="Conversation">
            {available ? (
              <p className="chat__msg chat__msg--assistant">{GREETING}</p>
            ) : (
              <p className="chat__msg chat__msg--assistant">The assistant isn't available right now. Tell our team what's wrong and we'll reply here and by SMS.</p>
            )}
            {messages.map((m, i) => (
              <p key={i} className={`chat__msg chat__msg--${m.role}`}>{m.text}</p>
            ))}
            {busy && <p className="chat__msg chat__msg--assistant chat__typing" role="status">Looking into it…</p>}
            {opened.length > 0 && (
              <p className="chat__note" role="status">
                Ticket {opened.map((n) => `#${n}`).join(", ")} opened. The reply will show on your{" "}
                <Link to="/dashboard/support" onClick={close}>Support page</Link> and arrive by SMS.
              </p>
            )}
            {(showForm || !available) && !opened.length && (
              <div className="chat__form">
                <TicketForm submitLabel="Send to our team"
                  onCreated={(t) => { setOpened((n) => [...n, t.id]); setShowForm(false); }} />
              </div>
            )}
          </div>

          {available && (
            <div className="chat__compose">
              {error && (
                <p className="chat__error" role="alert">
                  {error.message}{full && <> <button type="button" className="btn btn--link" onClick={newChat}>Start a new chat</button></>}
                </p>
              )}
              <div className="chat__row">
                <textarea ref={inputRef} className="field__input chat__input" rows={2} value={text} maxLength={MAX_CHARS}
                  aria-label="Your message" placeholder="Type your question…" disabled={busy || full}
                  onChange={(e) => setText(e.target.value)} onKeyDown={onKeyDown} />
                <button type="button" className="btn btn--primary btn--small" onClick={send} disabled={busy || full || !text.trim()}>
                  Send
                </button>
              </div>
              <p className="chat__foot">
                {!showForm && !opened.length && <button type="button" className="btn btn--link" onClick={() => setShowForm(true)}>Talk to a person</button>}
                {" "}<Link to="/dashboard/support" onClick={close}>My tickets</Link>
              </p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
