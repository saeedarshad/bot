import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const endRef = useRef(null);

  async function load() {
    setMessages(await api("/dev/chat"));
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function sendText(body) {
    if (!body || busy) return;
    setError(null);
    setBusy(true);
    // Optimistically show the outgoing patient message.
    setMessages((m) => [...m, { id: `tmp-${Date.now()}`, direction: "in", body }]);
    setText("");
    try {
      const res = await api("/dev/chat", { method: "POST", body: { message: body } });
      // Reload from the server so message ids/ordering match the DB.
      await load();
      if (res.silent) {
        setMessages((m) => [
          ...m,
          { id: `silent-${Date.now()}`, direction: "note", body: "(bot stayed silent)" },
        ]);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function send(e) {
    e.preventDefault();
    sendText(text.trim());
  }

  // Only the most recent bot message keeps its options tappable.
  const lastInteractiveId = [...messages]
    .reverse()
    .find((m) => m.direction === "out" && m.interactive?.options?.length)?.id;

  async function reset() {
    if (busy) return;
    await api("/dev/chat", { method: "DELETE" });
    setMessages([]);
    setError(null);
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-slate-500">
          Sandbox — you play the patient over WhatsApp. Each send is a live LLM call.
        </p>
        <button
          onClick={reset}
          disabled={busy}
          className="text-sm text-slate-500 hover:text-red-600 disabled:opacity-40"
        >
          Reset conversation
        </button>
      </div>

      <div className="bg-white border rounded-lg p-4 h-[60vh] overflow-y-auto space-y-2">
        {messages.length === 0 && !busy && (
          <div className="text-slate-400 text-sm text-center py-8">
            No messages yet. Say hello to the bot below.
          </div>
        )}
        {messages.map((m) => {
          if (m.direction === "note") {
            return (
              <div key={m.id} className="text-center text-xs text-slate-400 py-1">
                {m.body}
              </div>
            );
          }
          const options = m.interactive?.options || [];
          const tappable = m.id === lastInteractiveId && !busy;
          return (
            <div key={m.id} className={m.direction === "in" ? "flex flex-col items-end" : ""}>
              <div
                className={
                  "max-w-[80%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap " +
                  (m.direction === "in" ? "bg-indigo-600 text-white" : "bg-slate-100")
                }
              >
                {m.body}
              </div>
              {options.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5 max-w-[80%]">
                  {options.map((opt, i) => (
                    <button
                      key={i}
                      disabled={!tappable}
                      onClick={() => sendText(opt.title)}
                      title={opt.description || ""}
                      className={
                        "text-sm rounded-full border px-3 py-1.5 text-left transition " +
                        (tappable
                          ? "border-indigo-300 text-indigo-700 bg-white hover:bg-indigo-50"
                          : "border-slate-200 text-slate-400 bg-slate-50 cursor-default")
                      }
                    >
                      <span className="font-medium">{opt.title}</span>
                      {opt.description && (
                        <span className="block text-xs text-slate-400">{opt.description}</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {busy && (
          <div className="bg-slate-100 rounded-lg px-3 py-2 text-sm text-slate-400 max-w-[80%]">
            typing…
          </div>
        )}
        <div ref={endRef} />
      </div>

      {error && <div className="mt-2 text-sm text-red-600">{error}</div>}

      <form onSubmit={send} className="mt-3 flex gap-2">
        <input
          className="flex-1 border rounded px-3 py-2 text-sm"
          placeholder="Type a message as the patient…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={busy}
          autoFocus
        />
        <button
          disabled={busy || !text.trim()}
          className="bg-indigo-600 text-white rounded px-4 py-2 text-sm hover:bg-indigo-700 disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}
