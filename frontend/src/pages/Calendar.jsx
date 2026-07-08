import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  CalendarDays,
  AlertTriangle,
  MessageCircle,
  CheckCircle2,
  XCircle,
  Ban,
  CircleUser,
} from "lucide-react";
import { api } from "../api.js";
import { useAuth } from "../lib/auth.jsx";
import {
  Button,
  Badge,
  Card,
  Modal,
  Field,
  Select,
  Input,
  EmptyState,
  SkeletonRows,
  Avatar,
  toast,
  useConfirm,
} from "../components/ui/index.js";
import {
  dayKey,
  timeLabel,
  shiftDay,
  relativeDay,
  clinicWallTimeToUTC,
} from "../lib/format.js";

const STATUS_TONE = {
  pending: "warning",
  confirmed: "success",
  completed: "neutral",
  cancelled: "danger",
  no_show: "danger",
  rescheduled: "info",
};

const STATUS_ACCENT = {
  pending: "border-l-warning",
  confirmed: "border-l-success",
  completed: "border-l-border-strong",
  cancelled: "border-l-danger",
  no_show: "border-l-danger",
  rescheduled: "border-l-info",
};

function weekOf(day) {
  const base = new Date(day + "T12:00:00");
  const dow = (base.getDay() + 6) % 7; // Mon = 0
  const days = [];
  for (let i = -dow; i < 7 - dow; i++) {
    const d = new Date(base);
    d.setDate(d.getDate() + i);
    days.push(d.toISOString().slice(0, 10));
  }
  return days;
}

export default function Calendar() {
  const { me } = useAuth();
  const clinic = me?.clinic;
  const tz = clinic?.timezone || "America/New_York";
  const [day, setDay] = useState(() => dayKey(new Date().toISOString(), tz));
  const [appts, setAppts] = useState([]);
  const [services, setServices] = useState([]);
  const [patients, setPatients] = useState([]);
  const [costs, setCosts] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const confirm = useConfirm();

  async function load() {
    const [a, s, p, c] = await Promise.all([
      api("/appointments"),
      api("/services"),
      api("/patients"),
      api("/costs").catch(() => null),
    ]);
    setAppts(a);
    setServices(s);
    setPatients(p);
    setCosts(c);
    setLoading(false);
  }

  useEffect(() => {
    load().catch((e) => {
      setLoading(false);
      toast.error(e.message || "Failed to load calendar");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const countsByDay = useMemo(() => {
    const m = {};
    for (const a of appts) {
      if (a.status === "cancelled") continue;
      const k = dayKey(a.starts_at, tz);
      m[k] = (m[k] || 0) + 1;
    }
    return m;
  }, [appts, tz]);

  const dayAppts = useMemo(
    () =>
      appts
        .filter((a) => dayKey(a.starts_at, tz) === day)
        .sort((x, y) => x.starts_at.localeCompare(y.starts_at)),
    [appts, day, tz]
  );

  const atRiskCount = useMemo(() => dayAppts.filter((a) => a.at_risk).length, [dayAppts]);
  const week = useMemo(() => weekOf(day), [day]);
  const todayKey = dayKey(new Date().toISOString(), tz);

  async function setStatus(id, status) {
    await api(`/appointments/${id}`, { method: "PATCH", body: { status } });
    load();
  }

  async function lifecycle(id, action, label) {
    try {
      await api(`/appointments/${id}/${action}`, { method: "POST" });
      toast.success(label);
      load();
    } catch (e) {
      toast.error(e.message || "Action failed");
    }
  }

  async function cancelAppt(a) {
    const ok = await confirm({
      title: "Cancel appointment?",
      message: `Cancel ${a.patient_name || a.patient_phone}'s ${a.service_name}? This frees the slot and may offer it to your waitlist.`,
      confirmLabel: "Cancel appointment",
      danger: true,
    });
    if (!ok) return;
    try {
      await setStatus(a.id, "cancelled");
      toast.success("Appointment cancelled");
    } catch (e) {
      toast.error(e.message || "Could not cancel");
    }
  }

  return (
    <div className="space-y-5">
      {/* Header + week strip */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">
            {relativeDay(day, tz)}
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {new Date(day + "T12:00:00").toLocaleDateString(undefined, {
              month: "long",
              day: "numeric",
              year: "numeric",
            })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-lg border border-border bg-surface p-1">
            <button
              onClick={() => setDay(shiftDay(day, -1))}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-surface-hover hover:text-foreground"
              aria-label="Previous day"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              onClick={() => setDay(todayKey)}
              className="px-2 text-sm font-medium text-foreground hover:text-primary"
            >
              Today
            </button>
            <button
              onClick={() => setDay(shiftDay(day, 1))}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-surface-hover hover:text-foreground"
              aria-label="Next day"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className="h-9 rounded-lg border border-border bg-surface px-2.5 text-sm text-foreground shadow-xs focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/60"
          />
          <Button icon={Plus} onClick={() => setShowForm(true)}>
            New
          </Button>
        </div>
      </div>

      {/* 7-day strip */}
      <div className="grid grid-cols-7 gap-1.5">
        {week.map((k) => {
          const d = new Date(k + "T12:00:00");
          const active = k === day;
          const isToday = k === todayKey;
          const count = countsByDay[k] || 0;
          return (
            <button
              key={k}
              onClick={() => setDay(k)}
              className={
                "group flex flex-col items-center rounded-xl border py-2 transition-all " +
                (active
                  ? "border-primary bg-primary/10 shadow-xs"
                  : "border-border bg-surface hover:bg-surface-hover")
              }
            >
              <span
                className={
                  "text-[11px] font-medium uppercase " +
                  (active ? "text-primary" : "text-muted-foreground")
                }
              >
                {d.toLocaleDateString(undefined, { weekday: "short" })}
              </span>
              <span
                className={
                  "mt-0.5 flex h-7 w-7 items-center justify-center rounded-full text-sm font-semibold " +
                  (active
                    ? "bg-primary text-primary-foreground"
                    : isToday
                    ? "text-primary"
                    : "text-foreground")
                }
              >
                {d.getDate()}
              </span>
              <span className="mt-1 h-1.5 flex items-center">
                {count > 0 && (
                  <span
                    className={
                      "h-1.5 w-1.5 rounded-full " + (active ? "bg-primary" : "bg-border-strong")
                    }
                  />
                )}
              </span>
            </button>
          );
        })}
      </div>

      {/* Summary pills */}
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral" dot>
          {dayAppts.length} appointment{dayAppts.length === 1 ? "" : "s"}
        </Badge>
        {atRiskCount > 0 && (
          <Badge tone="warning">
            <AlertTriangle className="h-3 w-3" />
            {atRiskCount} at risk
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-2">
          {costs && (
            <Badge tone="neutral">
              <MessageCircle className="h-3 w-3" />
              {costs.currency} {costs.total} · {costs.message_count} msgs
            </Badge>
          )}
          {costs?.failed_deliveries > 0 && (
            <Badge tone="danger">{costs.failed_deliveries} failed to deliver</Badge>
          )}
        </div>
      </div>

      {/* Appointments */}
      {loading ? (
        <SkeletonRows rows={4} />
      ) : dayAppts.length === 0 ? (
        <EmptyState
          icon={CalendarDays}
          title="No appointments"
          description="Nothing scheduled for this day. Create one manually or let the AI receptionist book it."
          action={
            <Button icon={Plus} onClick={() => setShowForm(true)}>
              New appointment
            </Button>
          }
        />
      ) : (
        <div className="space-y-2.5">
          {dayAppts.map((a, i) => (
            <motion.div
              key={a.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.2) }}
            >
              <Card
                className={
                  "flex items-center gap-4 border-l-4 p-3.5 " +
                  (STATUS_ACCENT[a.status] || "border-l-border-strong") +
                  (a.at_risk ? " ring-1 ring-warning/40" : "")
                }
              >
                <div className="flex w-16 shrink-0 flex-col items-center">
                  <span className="text-sm font-bold tabular-nums text-foreground">
                    {timeLabel(a.starts_at, tz)}
                  </span>
                </div>
                <Avatar name={a.patient_name || a.patient_phone} size="md" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-semibold text-foreground">
                      {a.patient_name || a.patient_phone}
                    </span>
                    {a.at_risk && <Badge tone="warning">At risk</Badge>}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                    <span>{a.service_name}</span>
                    {a.source && (
                      <>
                        <span>·</span>
                        <span className="capitalize">{a.source.replace("_", " ")}</span>
                      </>
                    )}
                    {a.patient_confirmed_at && (
                      <>
                        <span>·</span>
                        <span className="inline-flex items-center gap-1 text-success">
                          <CheckCircle2 className="h-3 w-3" /> confirmed
                        </span>
                      </>
                    )}
                  </div>
                </div>
                <Badge tone={STATUS_TONE[a.status] || "neutral"} className="hidden sm:inline-flex">
                  {a.status.replace("_", " ")}
                </Badge>
                {["pending", "confirmed"].includes(a.status) && (
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={CheckCircle2}
                      onClick={() => lifecycle(a.id, "complete", "Marked completed")}
                      title="Mark completed"
                    >
                      <span className="hidden lg:inline">Complete</span>
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={XCircle}
                      onClick={() => lifecycle(a.id, "no_show", "Marked no-show")}
                      title="Mark no-show"
                    >
                      <span className="hidden lg:inline">No-show</span>
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={Ban}
                      onClick={() => cancelAppt(a)}
                      title="Cancel"
                      className="text-danger hover:bg-danger/10 hover:text-danger"
                    />
                  </div>
                )}
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      <NewAppointmentModal
        open={showForm}
        onClose={() => setShowForm(false)}
        services={services}
        patients={patients}
        defaultDay={day}
        tz={tz}
        onCreated={() => {
          setShowForm(false);
          toast.success("Appointment created");
          load();
        }}
      />
    </div>
  );
}

function NewAppointmentModal({ open, onClose, services, patients, defaultDay, tz, onCreated }) {
  const [patient, setPatient] = useState("");
  const [service, setService] = useState("");
  const [time, setTime] = useState("09:00");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const starts_at = clinicWallTimeToUTC(defaultDay, time, tz);
      await api("/appointments", {
        method: "POST",
        body: {
          patient: Number(patient),
          service: Number(service),
          starts_at,
          status: "confirmed",
        },
      });
      onCreated();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New appointment"
      description={`Booking for ${new Date(defaultDay + "T12:00:00").toLocaleDateString(undefined, {
        weekday: "long",
        month: "short",
        day: "numeric",
      })}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button form="new-appt-form" type="submit" loading={busy} icon={CircleUser}>
            Book appointment
          </Button>
        </>
      }
    >
      <form id="new-appt-form" onSubmit={submit} className="space-y-4">
        {error && (
          <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}
        <Field label="Patient" required>
          <Select value={patient} onChange={(e) => setPatient(e.target.value)} required>
            <option value="">Select a patient…</option>
            {patients.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name || p.phone_e164}
              </option>
            ))}
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Service" required>
            <Select value={service} onChange={(e) => setService(e.target.value)} required>
              <option value="">Select…</option>
              {services.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.duration_min}m)
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Time">
            <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
          </Field>
        </div>
      </form>
    </Modal>
  );
}
