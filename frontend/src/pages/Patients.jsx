import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Search, Users, MessageSquareText, ShieldOff, PhoneOff } from "lucide-react";
import { api } from "../api.js";
import { Card, Input, Avatar, Badge, EmptyState, Skeleton } from "../components/ui/index.js";
import { cn } from "../lib/cn.js";

function MessageBubble({ m }) {
  const inbound = m.direction === "in";
  return (
    <div className={cn("flex", inbound ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "max-w-[78%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm shadow-xs",
          inbound
            ? "rounded-bl-sm bg-muted text-foreground"
            : "rounded-br-sm bg-primary text-primary-foreground"
        )}
      >
        {m.body}
      </div>
    </div>
  );
}

export default function Patients() {
  const [patients, setPatients] = useState([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingThread, setLoadingThread] = useState(false);

  useEffect(() => {
    api("/patients")
      .then((p) => setPatients(p))
      .finally(() => setLoading(false));
  }, []);

  async function open(p) {
    setSelected(p);
    setLoadingThread(true);
    setMessages([]);
    try {
      setMessages(await api(`/patients/${p.id}/messages`));
    } finally {
      setLoadingThread(false);
    }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return patients;
    return patients.filter(
      (p) =>
        (p.name || "").toLowerCase().includes(q) ||
        (p.phone_e164 || "").toLowerCase().includes(q)
    );
  }, [patients, query]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-foreground">Patients</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {patients.length} patient{patients.length === 1 ? "" : "s"} · tap one to read their WhatsApp thread.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,340px)_1fr]">
        {/* List */}
        <Card className="flex h-[70vh] flex-col overflow-hidden">
          <div className="border-b border-border p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search name or number…"
                className="pl-9"
              />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto scrollbar-thin">
            {loading ? (
              <div className="space-y-2 p-3">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <Skeleton className="h-9 w-9 rounded-full" />
                    <div className="flex-1 space-y-1.5">
                      <Skeleton className="h-3 w-1/2" />
                      <Skeleton className="h-2.5 w-1/3" />
                    </div>
                  </div>
                ))}
              </div>
            ) : filtered.length === 0 ? (
              <div className="p-6 text-center text-sm text-muted-foreground">
                {patients.length === 0 ? "No patients yet." : "No matches."}
              </div>
            ) : (
              <ul className="divide-y divide-border">
                {filtered.map((p) => (
                  <li key={p.id}>
                    <button
                      onClick={() => open(p)}
                      className={cn(
                        "flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors",
                        selected?.id === p.id ? "bg-primary/10" : "hover:bg-surface-hover"
                      )}
                    >
                      <Avatar name={p.name || p.phone_e164} seed={p.phone_e164} size="md" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-foreground">
                          {p.name || "Unknown patient"}
                        </div>
                        <div className="truncate text-xs text-muted-foreground">
                          {p.phone_e164}
                        </div>
                      </div>
                      {p.opted_out_at && (
                        <Badge tone="danger">
                          <ShieldOff className="h-3 w-3" />
                        </Badge>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        {/* Detail */}
        <Card className="flex h-[70vh] flex-col overflow-hidden">
          {!selected ? (
            <div className="flex flex-1 items-center justify-center p-6">
              <EmptyState
                icon={Users}
                title="Select a patient"
                description="Pick someone on the left to view their conversation history."
                className="border-0 bg-transparent"
              />
            </div>
          ) : (
            <>
              <div className="flex items-center gap-3 border-b border-border p-4">
                <Avatar name={selected.name || selected.phone_e164} seed={selected.phone_e164} size="lg" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold text-foreground">
                    {selected.name || selected.phone_e164}
                  </div>
                  <div className="text-xs text-muted-foreground">{selected.phone_e164}</div>
                </div>
                <div className="flex items-center gap-2">
                  {selected.no_show_count > 0 && (
                    <Badge tone="warning">
                      {selected.no_show_count} no-show{selected.no_show_count === 1 ? "" : "s"}
                    </Badge>
                  )}
                  {selected.opted_out_at && (
                    <Badge tone="danger">
                      <PhoneOff className="h-3 w-3" /> opted out
                    </Badge>
                  )}
                </div>
              </div>

              <div className="flex-1 space-y-2.5 overflow-y-auto scrollbar-thin bg-grid p-4">
                {loadingThread ? (
                  <div className="space-y-3">
                    <Skeleton className="h-9 w-2/3 rounded-2xl" />
                    <Skeleton className="ml-auto h-9 w-1/2 rounded-2xl" />
                    <Skeleton className="h-14 w-3/5 rounded-2xl" />
                  </div>
                ) : messages.length === 0 ? (
                  <div className="flex h-full items-center justify-center">
                    <EmptyState
                      icon={MessageSquareText}
                      title="No messages"
                      description="This patient hasn't exchanged any messages yet."
                      className="border-0 bg-transparent"
                    />
                  </div>
                ) : (
                  messages.map((m) => (
                    <motion.div
                      key={m.id}
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.15 }}
                    >
                      <MessageBubble m={m} />
                    </motion.div>
                  ))
                )}
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
