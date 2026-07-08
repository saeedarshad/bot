import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Send, RotateCcw, Sparkles, Info } from "lucide-react";
import { api } from "../api.js";
import { Button, Badge, Card, useConfirm, toast } from "../components/ui/index.js";
import { cn } from "../lib/cn.js";

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  const confirm = useConfirm();

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
      toast.error(err.message || "Message failed");
    } finally {
      setBusy(false);
    }
  }

  function send(e) {
    e.preventDefault();
    sendText(text.trim());
  }

  const lastInteractiveId = [...messages]
    .reverse()
    .find((m) => m.direction === "out" && m.interactive?.options?.length)?.id;

  async function reset() {
    if (busy) return;
    const ok = await confirm({
      title: "Reset conversation?",
      message: "This deletes the demo patient and their entire sandbox conversation.",
      confirmLabel: "Reset",
      danger: true,
    });
    if (!ok) return;
    await api("/dev/chat", { method: "DELETE" });
    setMessages([]);
    toast.success("Sandbox reset");
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Chat sandbox</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            You play the patient over WhatsApp. Every send is one live LLM call.
          </p>
        </div>
        <Button variant="ghost" size="sm" icon={RotateCcw} onClick={reset} disabled={busy}>
          Reset
        </Button>
      </div>

      <div className="flex items-center gap-2 rounded-lg border border-info/25 bg-info/10 px-3 py-2 text-xs text-info">
        <Info className="h-3.5 w-3.5 shrink-0" />
        Live Anthropic call per message — Send is disabled while the bot is thinking.
      </div>

      <Card className="flex h-[62vh] flex-col overflow-hidden">
        {/* WhatsApp-style header */}
        <div className="flex items-center gap-3 border-b border-border bg-muted/40 px-4 py-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-primary to-accent">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <div className="flex-1">
            <div className="text-sm font-semibold text-foreground">Receptionaly bot</div>
            <div className="text-[11px] text-success">online</div>
          </div>
          <Badge tone="neutral">demo</Badge>
        </div>

        {/* Thread */}
        <div className="flex-1 space-y-2 overflow-y-auto scrollbar-thin bg-grid p-4">
          {messages.length === 0 && !busy && (
            <div className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
              No messages yet. Say hello to the bot below.
            </div>
          )}
          {messages.map((m) => {
            if (m.direction === "note") {
              return (
                <div key={m.id} className="py-1 text-center text-xs text-muted-foreground">
                  {m.body}
                </div>
              );
            }
            const options = m.interactive?.options || [];
            const tappable = m.id === lastInteractiveId && !busy;
            const inbound = m.direction === "in";
            return (
              <div key={m.id} className={cn("flex flex-col", inbound ? "items-end" : "items-start")}>
                <motion.div
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.15 }}
                  className={cn(
                    "max-w-[80%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm shadow-xs",
                    inbound
                      ? "rounded-br-sm bg-primary text-primary-foreground"
                      : "rounded-bl-sm bg-surface text-foreground ring-1 ring-border"
                  )}
                >
                  {m.body}
                </motion.div>
                {options.length > 0 && (
                  <div className="mt-1.5 flex max-w-[80%] flex-wrap gap-1.5">
                    {options.map((opt, i) => (
                      <button
                        key={i}
                        disabled={!tappable}
                        onClick={() => sendText(opt.title)}
                        title={opt.description || ""}
                        className={cn(
                          "rounded-full border px-3 py-1.5 text-left text-sm transition-colors",
                          tappable
                            ? "border-primary/40 bg-surface text-primary hover:bg-primary/10"
                            : "cursor-default border-border bg-muted/50 text-muted-foreground"
                        )}
                      >
                        <span className="font-medium">{opt.title}</span>
                        {opt.description && (
                          <span className="block text-xs text-muted-foreground">
                            {opt.description}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {busy && (
            <div className="flex items-start">
              <div className="flex items-center gap-1 rounded-2xl rounded-bl-sm bg-surface px-3.5 py-2.5 ring-1 ring-border">
                {[0, 1, 2].map((i) => (
                  <motion.span
                    key={i}
                    className="h-1.5 w-1.5 rounded-full bg-muted-foreground"
                    animate={{ opacity: [0.3, 1, 0.3] }}
                    transition={{ duration: 1, repeat: Infinity, delay: i * 0.2 }}
                  />
                ))}
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        {/* Composer */}
        <form onSubmit={send} className="flex items-center gap-2 border-t border-border p-3">
          <input
            className="h-10 flex-1 rounded-full border border-border bg-surface px-4 text-sm text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/60 disabled:opacity-60"
            placeholder="Type a message as the patient…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={busy}
            autoFocus
          />
          <Button type="submit" size="icon" disabled={busy || !text.trim()} aria-label="Send">
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </Card>
    </div>
  );
}
