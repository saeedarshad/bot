import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Building2,
  CalendarClock,
  Bot,
  Stethoscope,
  Clock,
  HelpCircle,
  Plus,
  Save,
  Copy,
  Trash2,
  Pencil,
  X,
  Info,
  Tag,
  DollarSign,
  UserRound,
} from "lucide-react";
import { api } from "../api.js";
import { cn } from "../lib/cn.js";
import {
  Card,
  CardBody,
  Button,
  Field,
  Input,
  Select,
  Textarea,
  Switch,
  Badge,
  Avatar,
  Tabs,
  Modal,
  EmptyState,
  PageSpinner,
  toast,
  useConfirm,
} from "../components/ui/index.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAYS = [
  { i: 0, label: "Monday" },
  { i: 1, label: "Tuesday" },
  { i: 2, label: "Wednesday" },
  { i: 3, label: "Thursday" },
  { i: 4, label: "Friday" },
  { i: 5, label: "Saturday" },
  { i: 6, label: "Sunday" },
];

const DETAIL_FIELDS = [
  ["name", "Clinic name"],
  ["timezone", "Timezone"],
  ["currency", "Currency"],
  ["phone_display", "Display phone"],
  ["emergency_phone", "Emergency phone"],
  ["address", "Address"],
  ["maps_link", "Maps link"],
  ["cancellation_policy", "Cancellation policy"],
  ["new_patient_form_url", "New-patient form URL"],
  ["accepted_insurance", "Accepted insurance"],
];

const BOOKING_FIELDS = [
  ["booking_horizon_days", "Booking horizon (days)"],
  ["min_notice_minutes", "Min notice (minutes)"],
  ["slot_granularity_minutes", "Slot granularity (minutes)"],
];

const TOGGLES = [
  ["reminders_enabled", "Appointment reminders", "Send confirmation & reminder messages."],
  ["no_show_recovery_enabled", "No-show recovery", "Re-engage patients who miss a visit."],
  ["recalls_enabled", "Recall campaigns", "Allow marketing recall sends."],
];

const TABS = [
  { id: "clinic", label: "Clinic details", icon: Building2 },
  { id: "booking", label: "Booking rules", icon: CalendarClock },
  { id: "automation", label: "Automation", icon: Bot },
  { id: "services", label: "Services", icon: Stethoscope },
  { id: "providers", label: "Providers", icon: UserRound },
  { id: "hours", label: "Working hours", icon: Clock },
  { id: "faqs", label: "FAQs", icon: HelpCircle },
];

export default function Settings() {
  const [tab, setTab] = useState("clinic");
  const [clinic, setClinic] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [services, setServices] = useState([]);
  const [practitioners, setPractitioners] = useState([]);
  const [rules, setRules] = useState([]);
  const [faqs, setFaqs] = useState([]);

  async function loadAll() {
    const [c, s, r, f, p] = await Promise.all([
      api("/settings"),
      api("/services"),
      api("/schedule-rules"),
      api("/faqs"),
      api("/practitioners").catch(() => []),
    ]);
    setClinic(c);
    setServices(s);
    setRules(r);
    setFaqs(f);
    setPractitioners(p || []);
  }

  useEffect(() => {
    loadAll();
  }, []);

  function setField(key, value) {
    setClinic((c) => ({ ...c, [key]: value }));
    setDirty(true);
  }

  async function saveClinic() {
    setSaving(true);
    try {
      const updated = await api("/settings", { method: "PATCH", body: clinic });
      setClinic(updated);
      setDirty(false);
      toast.success("Settings saved");
    } catch (e) {
      toast.error(e.message || "Could not save");
    } finally {
      setSaving(false);
    }
  }

  if (!clinic) return <PageSpinner label="Loading settings…" />;

  return (
    <div className="space-y-5 pb-20">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-foreground">Settings</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Clinic profile, booking rules, automation, services, hours, and FAQs.
        </p>
      </div>

      <Tabs tabs={TABS} value={tab} onChange={setTab} />

      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
        >
          {tab === "clinic" && (
            <Card>
              <CardBody className="grid gap-4 sm:grid-cols-2">
                {DETAIL_FIELDS.map(([key, label]) => (
                  <Field
                    key={key}
                    label={label}
                    className={key === "address" ? "sm:col-span-2" : ""}
                  >
                    <Input value={clinic[key] ?? ""} onChange={(e) => setField(key, e.target.value)} />
                  </Field>
                ))}
              </CardBody>
            </Card>
          )}

          {tab === "booking" && (
            <Card>
              <CardBody className="grid gap-4 sm:grid-cols-3">
                {BOOKING_FIELDS.map(([key, label]) => (
                  <Field key={key} label={label}>
                    <Input
                      type="number"
                      value={clinic[key] ?? ""}
                      onChange={(e) => setField(key, e.target.value)}
                    />
                  </Field>
                ))}
              </CardBody>
            </Card>
          )}

          {tab === "automation" && (
            <Card>
              <CardBody className="space-y-1">
                {TOGGLES.map(([key, label, hint]) => (
                  <div
                    key={key}
                    className="flex items-center justify-between gap-4 rounded-lg px-1 py-2.5"
                  >
                    <div>
                      <div className="text-sm font-medium text-foreground">{label}</div>
                      <div className="text-xs text-muted-foreground">{hint}</div>
                    </div>
                    <Switch checked={!!clinic[key]} onChange={(v) => setField(key, v)} label={label} />
                  </div>
                ))}
                <div className="grid gap-4 border-t border-border pt-4 sm:grid-cols-3">
                  <Field label="Owner phone (digest)">
                    <Input
                      value={clinic.owner_phone_e164 ?? ""}
                      onChange={(e) => setField("owner_phone_e164", e.target.value)}
                      placeholder="+15550000000"
                    />
                  </Field>
                  <Field label="Digest hour (0–23)">
                    <Input
                      type="number"
                      min="0"
                      max="23"
                      value={clinic.owner_digest_hour ?? ""}
                      onChange={(e) => setField("owner_digest_hour", e.target.value)}
                    />
                  </Field>
                  <Field label="Marketing min interval (days)">
                    <Input
                      type="number"
                      min="0"
                      value={clinic.marketing_min_interval_days ?? ""}
                      onChange={(e) => setField("marketing_min_interval_days", e.target.value)}
                    />
                  </Field>
                  <Field label="Prompt variant (A/B)" hint="v1 is the default prompt.">
                    <Select
                      value={clinic.prompt_variant || ""}
                      onChange={(e) => setField("prompt_variant", e.target.value)}
                    >
                      <option value="">v1 (default)</option>
                      <option value="v2">v2</option>
                    </Select>
                  </Field>
                </div>
              </CardBody>
            </Card>
          )}

          {tab === "services" && (
            <Services services={services} practitioners={practitioners} onChanged={loadAll} />
          )}

          {tab === "providers" && (
            <Providers practitioners={practitioners} onChanged={loadAll} />
          )}

          {tab === "hours" && <WorkingHours rules={rules} onChanged={loadAll} />}

          {tab === "faqs" && <Faqs faqs={faqs} onChanged={loadAll} />}
        </motion.div>
      </AnimatePresence>

      {/* Sticky save bar — visible whenever clinic/booking/automation fields change */}
      <AnimatePresence>
        {dirty && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            className="fixed inset-x-0 bottom-4 z-40 mx-auto flex w-fit items-center gap-3 rounded-full border border-border bg-surface px-4 py-2.5 shadow-lg"
          >
            <span className="text-sm text-muted-foreground">You have unsaved changes</span>
            <Button size="sm" icon={Save} loading={saving} onClick={saveClinic}>
              Save changes
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Working hours — a 7-day week grid (Calendly/Square style)          */
/* ------------------------------------------------------------------ */

const toHM = (t) => (t || "").slice(0, 5); // "09:00:00" -> "09:00"

function WorkingHours({ rules, onChanged }) {
  const [busy, setBusy] = useState(false);
  // Local mirror of each rule's times so editing a time input is snappy and
  // doesn't lose focus (we persist in the background, no full reload per edit).
  const [times, setTimes] = useState({});

  useEffect(() => {
    const t = {};
    for (const r of rules) t[r.id] = { start: toHM(r.start_time), end: toHM(r.end_time) };
    setTimes(t);
  }, [rules]);

  const byDay = useMemo(() => {
    const m = {};
    for (let i = 0; i < 7; i++) m[i] = [];
    for (const r of rules) if (m[r.weekday]) m[r.weekday].push(r);
    for (let i = 0; i < 7; i++)
      m[i].sort((a, b) => toHM(a.start_time).localeCompare(toHM(b.start_time)));
    return m;
  }, [rules]);

  const openDays = Object.values(byDay).filter((v) => v.length).length;

  async function run(fn) {
    setBusy(true);
    try {
      await fn();
      await onChanged();
    } catch (e) {
      toast.error(e.message || "Could not update hours");
    } finally {
      setBusy(false);
    }
  }

  const addInterval = (wd) =>
    run(() =>
      api("/schedule-rules", {
        method: "POST",
        body: { weekday: wd, start_time: "09:00", end_time: "17:00" },
      })
    );

  const removeInterval = (id) =>
    run(() => api(`/schedule-rules/${id}`, { method: "DELETE" }));

  const toggleDay = (wd, isOpen) =>
    run(async () => {
      if (isOpen) {
        for (const r of byDay[wd]) await api(`/schedule-rules/${r.id}`, { method: "DELETE" });
      } else {
        await api("/schedule-rules", {
          method: "POST",
          body: { weekday: wd, start_time: "09:00", end_time: "17:00" },
        });
      }
    });

  const copyToAll = (wd) =>
    run(async () => {
      const src = byDay[wd].map((r) => ({ start_time: toHM(r.start_time), end_time: toHM(r.end_time) }));
      for (let d = 0; d < 7; d++) {
        if (d === wd) continue;
        for (const r of byDay[d]) await api(`/schedule-rules/${r.id}`, { method: "DELETE" });
        for (const s of src) await api("/schedule-rules", { method: "POST", body: { weekday: d, ...s } });
      }
    });

  // Persist a time edit in the background; controlled by local `times` state.
  function setTime(id, field, value) {
    setTimes((p) => ({ ...p, [id]: { ...p[id], [field]: value } }));
    if (!value) return;
    api(`/schedule-rules/${id}`, {
      method: "PATCH",
      body: { [field === "start" ? "start_time" : "end_time"]: value },
    }).catch((e) => {
      toast.error(e.message || "Could not save time");
      onChanged();
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2.5 rounded-xl border border-info/25 bg-info/10 px-3.5 py-2.5 text-sm text-info">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          Set the hours patients can book each day. Toggle a day off to mark it closed, or add a
          second block for a lunch break.
        </span>
      </div>

      <Card>
        <CardBody className="p-0">
          <div className="divide-y divide-border">
            {DAYS.map((d) => {
              const intervals = byDay[d.i];
              const isOpen = intervals.length > 0;
              return (
                <div
                  key={d.i}
                  className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-start sm:gap-6"
                >
                  <div className="flex w-40 shrink-0 items-center gap-3">
                    <Switch
                      checked={isOpen}
                      onChange={() => toggleDay(d.i, isOpen)}
                      disabled={busy}
                      label={d.label}
                    />
                    <span
                      className={cn(
                        "text-sm font-medium",
                        isOpen ? "text-foreground" : "text-muted-foreground"
                      )}
                    >
                      {d.label}
                    </span>
                  </div>

                  <div className="min-w-0 flex-1">
                    {!isOpen ? (
                      <span className="inline-flex h-9 items-center text-sm text-muted-foreground">
                        Closed
                      </span>
                    ) : (
                      <div className="space-y-2">
                        {intervals.map((r) => (
                          <div key={r.id} className="flex items-center gap-2">
                            <Input
                              type="time"
                              value={times[r.id]?.start ?? toHM(r.start_time)}
                              onChange={(e) => setTime(r.id, "start", e.target.value)}
                              disabled={busy}
                              className="w-32"
                            />
                            <span className="text-muted-foreground">–</span>
                            <Input
                              type="time"
                              value={times[r.id]?.end ?? toHM(r.end_time)}
                              onChange={(e) => setTime(r.id, "end", e.target.value)}
                              disabled={busy}
                              className="w-32"
                            />
                            <button
                              type="button"
                              onClick={() => removeInterval(r.id)}
                              disabled={busy}
                              className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger disabled:opacity-50"
                              aria-label="Remove time block"
                              title="Remove"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </div>
                        ))}
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1">
                          <button
                            type="button"
                            onClick={() => addInterval(d.i)}
                            disabled={busy}
                            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline disabled:opacity-50"
                          >
                            <Plus className="h-3.5 w-3.5" /> Add hours
                          </button>
                          <button
                            type="button"
                            onClick={() => copyToAll(d.i)}
                            disabled={busy}
                            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
                            title="Copy these hours to every other day"
                          >
                            <Copy className="h-3.5 w-3.5" /> Copy to all days
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </CardBody>
      </Card>

      <p className="text-xs text-muted-foreground">
        {openDays} day{openDays === 1 ? "" : "s"} open per week.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  FAQs — reviewable cards with inline edit / delete + guided modal   */
/* ------------------------------------------------------------------ */

const parseKeywords = (s) =>
  String(s || "")
    .split(/[\n,]+/)
    .map((x) => x.trim())
    .filter(Boolean);

function Faqs({ faqs, onChanged }) {
  const confirm = useConfirm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  function openNew() {
    setEditing(null);
    setModalOpen(true);
  }
  function openEdit(f) {
    setEditing(f);
    setModalOpen(true);
  }

  async function remove(f) {
    const ok = await confirm({
      title: "Delete this FAQ?",
      message: `The bot will stop answering “${f.category || "this topic"}” automatically. This can't be undone.`,
      confirmLabel: "Delete FAQ",
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/faqs/${f.id}`, { method: "DELETE" });
      toast.success("FAQ deleted");
      await onChanged();
    } catch (e) {
      toast.error(e.message);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-2.5 rounded-xl border border-info/25 bg-info/10 px-3.5 py-2.5 text-sm text-info">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            The AI receptionist answers these instantly. Add a topic, a few ways patients might ask,
            and the exact reply to give.
          </span>
        </div>
        <Button icon={Plus} onClick={openNew} className="shrink-0">
          Add FAQ
        </Button>
      </div>

      {faqs.length === 0 ? (
        <EmptyState
          icon={HelpCircle}
          title="No FAQs yet"
          description="Add your first FAQ so the bot can answer common questions like parking, insurance, or hours."
          action={
            <Button icon={Plus} onClick={openNew}>
              Add FAQ
            </Button>
          }
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {faqs.map((f) => {
            const keywords = parseKeywords(f.question_patterns);
            return (
              <Card key={f.id} className="group flex flex-col p-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <Badge tone="primary">
                    <Tag className="h-3 w-3" />
                    {f.category || "General"}
                  </Badge>
                  <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                    <button
                      type="button"
                      onClick={() => openEdit(f)}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
                      aria-label="Edit FAQ"
                      title="Edit"
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(f)}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger"
                      aria-label="Delete FAQ"
                      title="Delete"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
                <p className="flex-1 text-sm text-foreground">{f.answer_en}</p>
                {keywords.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5 border-t border-border pt-3">
                    {keywords.slice(0, 6).map((k, i) => (
                      <span
                        key={i}
                        className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground"
                      >
                        {k}
                      </span>
                    ))}
                    {keywords.length > 6 && (
                      <span className="px-1 text-[11px] text-subtle-foreground">
                        +{keywords.length - 6}
                      </span>
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      <FaqModal
        open={modalOpen}
        initial={editing}
        onClose={() => setModalOpen(false)}
        onSaved={async () => {
          setModalOpen(false);
          await onChanged();
        }}
      />
    </div>
  );
}

function FaqModal({ open, initial, onClose, onSaved }) {
  const [category, setCategory] = useState("");
  const [keywords, setKeywords] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setCategory(initial?.category || "");
      setKeywords(initial?.question_patterns || "");
      setAnswer(initial?.answer_en || "");
    }
  }, [open, initial]);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    const body = {
      category,
      question_patterns: parseKeywords(keywords).join("\n"),
      answer_en: answer,
    };
    try {
      if (initial) await api(`/faqs/${initial.id}`, { method: "PATCH", body });
      else await api("/faqs", { method: "POST", body });
      toast.success(initial ? "FAQ updated" : "FAQ added");
      onSaved();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={initial ? "Edit FAQ" : "Add FAQ"}
      description="Teach the AI receptionist how to answer a common question."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button form="faq-form" type="submit" loading={busy}>
            {initial ? "Save changes" : "Add FAQ"}
          </Button>
        </>
      }
    >
      <form id="faq-form" onSubmit={submit} className="space-y-4">
        <Field label="Topic" hint="A short label for this question, e.g. Parking or Insurance.">
          <Input
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="Parking"
            autoFocus
            required
          />
        </Field>
        <Field
          label="How patients might ask"
          hint="One phrasing per line (or comma-separated). Helps the bot recognize the question."
        >
          <Textarea
            rows={3}
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
            placeholder={"where do I park\nis there parking\nparking garage"}
          />
        </Field>
        <Field label="Answer" hint="Exactly what the bot should reply.">
          <Textarea
            rows={3}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="There's free parking in the lot behind our building."
            required
          />
        </Field>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/*  Services — manageable list with add / edit / activate / delete     */
/* ------------------------------------------------------------------ */

function providerLabel(service, practitioners) {
  const ids = service.practitioners || [];
  if (!ids.length) return null; // empty = any provider
  const names = ids
    .map((id) => practitioners.find((p) => p.id === id)?.name)
    .filter(Boolean);
  if (!names.length) return null;
  return names.length <= 2 ? names.join(", ") : `${names.length} providers`;
}

function Services({ services, practitioners, onChanged }) {
  const confirm = useConfirm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [busyId, setBusyId] = useState(null);

  async function toggleActive(s) {
    setBusyId(s.id);
    try {
      await api(`/services/${s.id}`, { method: "PATCH", body: { is_active: !s.is_active } });
      toast.success(s.is_active ? "Service deactivated" : "Service activated");
      await onChanged();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusyId(null);
    }
  }

  async function remove(s) {
    const ok = await confirm({
      title: `Delete ${s.name}?`,
      message:
        "This permanently removes the service. If it already has appointments, deactivate it instead — those keep the service on record.",
      confirmLabel: "Delete service",
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/services/${s.id}`, { method: "DELETE" });
      toast.success("Service deleted");
      await onChanged();
    } catch (e) {
      // Appointment.service is PROTECT — deleting a booked service is blocked.
      toast.error("Can't delete a service that has appointments. Deactivate it instead.");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-2.5 rounded-xl border border-info/25 bg-info/10 px-3.5 py-2.5 text-sm text-info">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            These are what patients can book. Duration and buffer shape your availability; only
            active services are offered.
          </span>
        </div>
        <Button
          icon={Plus}
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
          className="shrink-0"
        >
          Add service
        </Button>
      </div>

      {services.length === 0 ? (
        <EmptyState
          icon={Stethoscope}
          title="No services yet"
          description="Add your first service — like a cleaning or checkup — so patients can book it."
          action={
            <Button
              icon={Plus}
              onClick={() => {
                setEditing(null);
                setModalOpen(true);
              }}
            >
              Add service
            </Button>
          }
        />
      ) : (
        <Card>
          <CardBody className="p-0">
            <div className="divide-y divide-border">
              {services.map((s) => {
                const price = s.price_display || (s.price_min != null ? `$${s.price_min}` : null);
                const providers = providerLabel(s, practitioners);
                return (
                  <div key={s.id} className="flex items-center gap-4 px-4 py-3.5">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            "truncate font-medium",
                            s.is_active ? "text-foreground" : "text-muted-foreground"
                          )}
                        >
                          {s.name}
                        </span>
                        {!s.is_active && <Badge tone="neutral">inactive</Badge>}
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {s.duration_min} min
                        </span>
                        {price && (
                          <span className="inline-flex items-center gap-1">
                            <DollarSign className="h-3 w-3" />
                            {price}
                          </span>
                        )}
                        {s.buffer_after_min > 0 && <span>+{s.buffer_after_min}m buffer</span>}
                        <span className="inline-flex items-center gap-1">
                          <Stethoscope className="h-3 w-3" />
                          {providers || "Any provider"}
                        </span>
                      </div>
                    </div>
                    <Switch
                      checked={s.is_active}
                      onChange={() => toggleActive(s)}
                      disabled={busyId === s.id}
                      label={`Toggle ${s.name}`}
                    />
                    <div className="flex items-center gap-0.5">
                      <button
                        type="button"
                        onClick={() => {
                          setEditing(s);
                          setModalOpen(true);
                        }}
                        className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
                        aria-label="Edit service"
                        title="Edit"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(s)}
                        className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger"
                        aria-label="Delete service"
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardBody>
        </Card>
      )}

      <ServiceModal
        open={modalOpen}
        initial={editing}
        practitioners={practitioners}
        onClose={() => setModalOpen(false)}
        onSaved={async () => {
          setModalOpen(false);
          await onChanged();
        }}
      />
    </div>
  );
}

const BLANK_SERVICE = {
  name: "",
  duration_min: 30,
  price_display: "",
  price_min: "",
  buffer_after_min: 0,
  is_active: true,
  practitioners: [],
};

function ServiceModal({ open, initial, practitioners, onClose, onSaved }) {
  const [form, setForm] = useState(BLANK_SERVICE);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(
      initial
        ? {
            name: initial.name || "",
            duration_min: initial.duration_min ?? 30,
            price_display: initial.price_display || "",
            price_min: initial.price_min ?? "",
            buffer_after_min: initial.buffer_after_min ?? 0,
            is_active: initial.is_active ?? true,
            practitioners: initial.practitioners || [],
          }
        : BLANK_SERVICE
    );
  }, [open, initial]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const toggleProvider = (id) =>
    setForm((f) => ({
      ...f,
      practitioners: f.practitioners.includes(id)
        ? f.practitioners.filter((x) => x !== id)
        : [...f.practitioners, id],
    }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    const body = {
      name: form.name,
      duration_min: Number(form.duration_min) || 0,
      price_display: form.price_display,
      price_min: form.price_min === "" ? null : Number(form.price_min),
      buffer_after_min: Number(form.buffer_after_min) || 0,
      is_active: form.is_active,
      practitioners: form.practitioners,
    };
    try {
      if (initial) await api(`/services/${initial.id}`, { method: "PATCH", body });
      else await api("/services", { method: "POST", body });
      toast.success(initial ? "Service updated" : "Service added");
      onSaved();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={initial ? "Edit service" : "Add service"}
      description="What patients can book, and how long it takes."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button form="service-form" type="submit" loading={busy}>
            {initial ? "Save changes" : "Add service"}
          </Button>
        </>
      }
    >
      <form id="service-form" onSubmit={submit} className="space-y-4">
        <Field label="Name" required>
          <Input
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="Cleaning"
            autoFocus
            required
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Duration (minutes)" required>
            <Input
              type="number"
              min="1"
              value={form.duration_min}
              onChange={(e) => set("duration_min", e.target.value)}
              required
            />
          </Field>
          <Field label="Buffer after (minutes)" hint="Cleanup / turnover time.">
            <Input
              type="number"
              min="0"
              value={form.buffer_after_min}
              onChange={(e) => set("buffer_after_min", e.target.value)}
            />
          </Field>
          <Field label="Price shown to patients" hint="Free text, e.g. from $150.">
            <Input
              value={form.price_display}
              onChange={(e) => set("price_display", e.target.value)}
              placeholder="from $150"
            />
          </Field>
          <Field label="Price value" hint="Number used for revenue reporting. Optional.">
            <Input
              type="number"
              min="0"
              step="0.01"
              value={form.price_min}
              onChange={(e) => set("price_min", e.target.value)}
              placeholder="150"
            />
          </Field>
        </div>

        {practitioners.length > 0 && (
          <Field
            label="Providers"
            hint="Who can perform this service. Leave all off to allow any provider."
          >
            <div className="flex flex-wrap gap-2">
              {practitioners.map((p) => {
                const on = form.practitioners.includes(p.id);
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => toggleProvider(p.id)}
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors",
                      on
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:bg-surface-hover"
                    )}
                  >
                    {p.name}
                  </button>
                );
              })}
            </div>
          </Field>
        )}

        <label className="flex items-center justify-between rounded-lg border border-border px-3.5 py-2.5">
          <span>
            <span className="block text-sm font-medium text-foreground">Active</span>
            <span className="block text-xs text-muted-foreground">
              Only active services are offered to patients.
            </span>
          </span>
          <Switch checked={form.is_active} onChange={(v) => set("is_active", v)} label="Active" />
        </label>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/*  Providers (practitioners) — the people who see patients            */
/* ------------------------------------------------------------------ */

function Providers({ practitioners, onChanged }) {
  const confirm = useConfirm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [busyId, setBusyId] = useState(null);

  async function toggleActive(p) {
    setBusyId(p.id);
    try {
      await api(`/practitioners/${p.id}`, { method: "PATCH", body: { is_active: !p.is_active } });
      toast.success(p.is_active ? "Provider deactivated" : "Provider activated");
      await onChanged();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusyId(null);
    }
  }

  async function remove(p) {
    const ok = await confirm({
      title: `Remove ${p.name}?`,
      message:
        "Past appointments stay on record but become unassigned, and this provider's own working-hours overrides are deleted. To keep them on record, deactivate instead.",
      confirmLabel: "Remove provider",
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/practitioners/${p.id}`, { method: "DELETE" });
      toast.success("Provider removed");
      await onChanged();
    } catch (e) {
      toast.error(e.message);
    }
  }

  function openNew() {
    setEditing(null);
    setModalOpen(true);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-2.5 rounded-xl border border-info/25 bg-info/10 px-3.5 py-2.5 text-sm text-info">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            The people who see patients. Assign them to services here, and only active providers
            take bookings.
          </span>
        </div>
        <Button icon={Plus} onClick={openNew} className="shrink-0">
          Add provider
        </Button>
      </div>

      {practitioners.length === 0 ? (
        <EmptyState
          icon={UserRound}
          title="No providers yet"
          description="Add the doctors or specialists who see patients so services can be assigned to them."
          action={
            <Button icon={Plus} onClick={openNew}>
              Add provider
            </Button>
          }
        />
      ) : (
        <Card>
          <CardBody className="p-0">
            <div className="divide-y divide-border">
              {practitioners.map((p) => (
                <div key={p.id} className="flex items-center gap-4 px-4 py-3.5">
                  <Avatar name={p.name} size="md" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "truncate font-medium",
                          p.is_active ? "text-foreground" : "text-muted-foreground"
                        )}
                      >
                        {p.name}
                      </span>
                      {!p.is_active && <Badge tone="neutral">inactive</Badge>}
                    </div>
                    {(p.title || p.specialty) && (
                      <div className="mt-0.5 truncate text-xs text-muted-foreground">
                        {[p.title, p.specialty].filter(Boolean).join(" · ")}
                      </div>
                    )}
                  </div>
                  <Switch
                    checked={p.is_active}
                    onChange={() => toggleActive(p)}
                    disabled={busyId === p.id}
                    label={`Toggle ${p.name}`}
                  />
                  <div className="flex items-center gap-0.5">
                    <button
                      type="button"
                      onClick={() => {
                        setEditing(p);
                        setModalOpen(true);
                      }}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
                      aria-label="Edit provider"
                      title="Edit"
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(p)}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger"
                      aria-label="Remove provider"
                      title="Remove"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      <ProviderModal
        open={modalOpen}
        initial={editing}
        onClose={() => setModalOpen(false)}
        onSaved={async () => {
          setModalOpen(false);
          await onChanged();
        }}
      />
    </div>
  );
}

const BLANK_PROVIDER = { name: "", title: "", specialty: "", is_active: true };

function ProviderModal({ open, initial, onClose, onSaved }) {
  const [form, setForm] = useState(BLANK_PROVIDER);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(
      initial
        ? {
            name: initial.name || "",
            title: initial.title || "",
            specialty: initial.specialty || "",
            is_active: initial.is_active ?? true,
          }
        : BLANK_PROVIDER
    );
  }, [open, initial]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      if (initial) await api(`/practitioners/${initial.id}`, { method: "PATCH", body: form });
      else await api("/practitioners", { method: "POST", body: form });
      toast.success(initial ? "Provider updated" : "Provider added");
      onSaved();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={initial ? "Edit provider" : "Add provider"}
      description="Someone who sees patients at your clinic."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button form="provider-form" type="submit" loading={busy}>
            {initial ? "Save changes" : "Add provider"}
          </Button>
        </>
      }
    >
      <form id="provider-form" onSubmit={submit} className="space-y-4">
        <Field label="Name" required>
          <Input
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="Dr. Alex Rivera"
            autoFocus
            required
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Title" hint="e.g. DDS, MD, Hygienist.">
            <Input value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="DDS" />
          </Field>
          <Field label="Specialty" hint="Optional.">
            <Input
              value={form.specialty}
              onChange={(e) => set("specialty", e.target.value)}
              placeholder="General Dentistry"
            />
          </Field>
        </div>
        <label className="flex items-center justify-between rounded-lg border border-border px-3.5 py-2.5">
          <span>
            <span className="block text-sm font-medium text-foreground">Active</span>
            <span className="block text-xs text-muted-foreground">
              Only active providers take bookings.
            </span>
          </span>
          <Switch checked={form.is_active} onChange={(v) => set("is_active", v)} label="Active" />
        </label>
      </form>
    </Modal>
  );
}
