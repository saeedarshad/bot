import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Search,
  Users,
  MessageSquareText,
  ShieldOff,
  PhoneOff,
  Plus,
  CalendarDays,
  Stethoscope,
  UserPlus,
} from "lucide-react";
import { api } from "../api.js";
import { useAuth } from "../lib/auth.jsx";
import {
  Card,
  Input,
  Textarea,
  Avatar,
  Badge,
  Button,
  EmptyState,
  Field,
  Modal,
  Skeleton,
  toast,
} from "../components/ui/index.js";
import { cn } from "../lib/cn.js";
import { timeLabel } from "../lib/format.js";

const STATUS_TONE = {
  pending: "warning",
  confirmed: "success",
  completed: "neutral",
  cancelled: "danger",
  no_show: "danger",
  rescheduled: "info",
};

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

function visitDateLabel(iso, tz) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(iso));
}

function Visits({ visits, loading, tz }) {
  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full rounded-xl" />
        ))}
      </div>
    );
  }
  if (visits.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState
          icon={CalendarDays}
          title="No visits yet"
          description="Appointments booked by this patient (or for them) will show up here."
          className="border-0 bg-transparent"
        />
      </div>
    );
  }
  const completed = visits.filter((v) => v.status === "completed").length;
  const noShows = visits.filter((v) => v.status === "no_show").length;
  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <Badge tone="neutral">{visits.length} total</Badge>
        <Badge tone="success">{completed} completed</Badge>
        {noShows > 0 && <Badge tone="danger">{noShows} no-show{noShows === 1 ? "" : "s"}</Badge>}
      </div>
      <ul className="space-y-2">
        {visits.map((v) => (
          <li
            key={v.id}
            className="flex items-center gap-3 rounded-xl border border-border bg-surface px-3.5 py-2.5"
          >
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-foreground">
                {visitDateLabel(v.starts_at, tz)} · {timeLabel(v.starts_at, tz)}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                <span>{v.service_name}</span>
                {v.practitioner_name && (
                  <span className="inline-flex items-center gap-1">
                    <Stethoscope className="h-3 w-3" />
                    {v.practitioner_name}
                  </span>
                )}
                {v.source && <span className="capitalize">· {v.source.replace("_", " ")}</span>}
              </div>
            </div>
            <Badge tone={STATUS_TONE[v.status] || "neutral"}>{v.status.replace("_", " ")}</Badge>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Patients() {
  const { me } = useAuth();
  const tz = me?.clinic?.timezone || "America/New_York";
  const [patients, setPatients] = useState([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [visits, setVisits] = useState([]);
  const [detailTab, setDetailTab] = useState("visits");
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [showAdd, setShowAdd] = useState(false);

  async function loadPatients() {
    const p = await api("/patients");
    setPatients(p);
    return p;
  }

  useEffect(() => {
    loadPatients().finally(() => setLoading(false));
  }, []);

  async function open(p) {
    setSelected(p);
    setLoadingDetail(true);
    setMessages([]);
    setVisits([]);
    try {
      const [msgs, appts] = await Promise.all([
        api(`/patients/${p.id}/messages`),
        api(`/patients/${p.id}/appointments`),
      ]);
      setMessages(msgs);
      setVisits(appts);
    } finally {
      setLoadingDetail(false);
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
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Patients</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {patients.length} patient{patients.length === 1 ? "" : "s"} · tap one to see their
            visits and WhatsApp thread.
          </p>
        </div>
        <Button icon={Plus} onClick={() => setShowAdd(true)} className="shrink-0">
          Add patient
        </Button>
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
                description="Pick someone on the left to view their visit history and conversation."
                className="border-0 bg-transparent"
              />
            </div>
          ) : (
            <>
              <div className="border-b border-border p-4">
                <div className="flex items-center gap-3">
                  <Avatar
                    name={selected.name || selected.phone_e164}
                    seed={selected.phone_e164}
                    size="lg"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold text-foreground">
                      {selected.name || selected.phone_e164}
                    </div>
                    <div className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                      <span>{selected.phone_e164}</span>
                      {selected.preferred_practitioner_name && (
                        <span>· usually sees {selected.preferred_practitioner_name}</span>
                      )}
                    </div>
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
                <div className="mt-3 flex gap-1">
                  {[
                    { id: "visits", label: "Visits", icon: CalendarDays },
                    { id: "messages", label: "Conversation", icon: MessageSquareText },
                  ].map((t) => (
                    <button
                      key={t.id}
                      onClick={() => setDetailTab(t.id)}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                        detailTab === t.id
                          ? "bg-primary/10 text-primary"
                          : "text-muted-foreground hover:bg-surface-hover hover:text-foreground"
                      )}
                    >
                      <t.icon className="h-4 w-4" />
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>

              {detailTab === "visits" ? (
                <div className="flex-1 overflow-y-auto scrollbar-thin">
                  <Visits visits={visits} loading={loadingDetail} tz={tz} />
                </div>
              ) : (
                <div className="flex-1 space-y-2.5 overflow-y-auto scrollbar-thin bg-grid p-4">
                  {loadingDetail ? (
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
              )}
            </>
          )}
        </Card>
      </div>

      <AddPatientModal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={async (created) => {
          setShowAdd(false);
          toast.success("Patient added");
          await loadPatients();
          open(created);
        }}
      />
    </div>
  );
}

function AddPatientModal({ open, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setName("");
      setPhone("");
      setNotes("");
      setError(null);
    }
  }, [open]);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await api("/patients", {
        method: "POST",
        body: { name, phone_e164: phone, notes },
      });
      onCreated(created);
    } catch (err) {
      setError(err.message || "Could not add patient");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add patient"
      description="For walk-ins or phone bookings. Patients who message the clinic are added automatically."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button form="add-patient-form" type="submit" loading={busy} icon={UserPlus}>
            Add patient
          </Button>
        </>
      }
    >
      <form id="add-patient-form" onSubmit={submit} className="space-y-4">
        {error && (
          <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}
        <Field label="Name">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Jordan Lee"
            autoFocus
          />
        </Field>
        <Field
          label="WhatsApp number"
          required
          info="Must be the patient's WhatsApp number in international format (+ country code) — it's how reminders and confirmations reach them."
          hint="E.g. +1 555 987 6543"
        >
          <Input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+15559876543"
            required
          />
        </Field>
        <Field label="Notes" hint="Internal only — patients never see this.">
          <Textarea
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Prefers morning appointments."
          />
        </Field>
      </form>
    </Modal>
  );
}
