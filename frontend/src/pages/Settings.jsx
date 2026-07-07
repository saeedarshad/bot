import { useEffect, useState } from "react";
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
} from "lucide-react";
import { api } from "../api.js";
import {
  Card,
  CardHeader,
  CardBody,
  Button,
  Field,
  Input,
  Select,
  Switch,
  Badge,
  PageSpinner,
  toast,
} from "../components/ui/index.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

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

export default function Settings() {
  const [clinic, setClinic] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [services, setServices] = useState([]);
  const [rules, setRules] = useState([]);
  const [faqs, setFaqs] = useState([]);

  async function loadAll() {
    const [c, s, r, f] = await Promise.all([
      api("/settings"),
      api("/services"),
      api("/schedule-rules"),
      api("/faqs"),
    ]);
    setClinic(c);
    setServices(s);
    setRules(r);
    setFaqs(f);
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

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Building2 className="h-4 w-4 text-primary" /> Clinic details
            </span>
          }
        />
        <CardBody className="grid gap-4 sm:grid-cols-2">
          {DETAIL_FIELDS.map(([key, label]) => (
            <Field key={key} label={label} className={key === "address" ? "sm:col-span-2" : ""}>
              <Input value={clinic[key] ?? ""} onChange={(e) => setField(key, e.target.value)} />
            </Field>
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <CalendarClock className="h-4 w-4 text-primary" /> Booking rules
            </span>
          }
        />
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

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-primary" /> Automation & messaging
            </span>
          }
        />
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
              <Switch
                checked={!!clinic[key]}
                onChange={(v) => setField(key, v)}
                label={label}
              />
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

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Stethoscope className="h-4 w-4 text-primary" /> Services
            </span>
          }
        />
        <CardBody>
          <ul className="mb-4 divide-y divide-border">
            {services.length === 0 && (
              <li className="py-2 text-sm text-muted-foreground">No services yet.</li>
            )}
            {services.map((s) => (
              <li key={s.id} className="flex items-center justify-between py-2.5 text-sm">
                <span className="text-foreground">
                  <span className="font-medium">{s.name}</span>{" "}
                  <span className="text-muted-foreground">
                    · {s.duration_min}m{s.price_display ? ` · ${s.price_display}` : ""}
                  </span>
                </span>
                <Badge tone={s.is_active ? "success" : "neutral"}>
                  {s.is_active ? "active" : "inactive"}
                </Badge>
              </li>
            ))}
          </ul>
          <AddService onAdded={loadAll} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-primary" /> Working hours
            </span>
          }
        />
        <CardBody>
          <ul className="mb-4 divide-y divide-border">
            {rules.length === 0 && (
              <li className="py-2 text-sm text-muted-foreground">No hours set.</li>
            )}
            {rules.map((r) => (
              <li key={r.id} className="flex items-center justify-between py-2.5 text-sm">
                <span className="font-medium text-foreground">{WEEKDAYS[r.weekday]}</span>
                <span className="tabular-nums text-muted-foreground">
                  {r.start_time}–{r.end_time}
                </span>
              </li>
            ))}
          </ul>
          <AddRule onAdded={loadAll} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <HelpCircle className="h-4 w-4 text-primary" /> FAQ answers
            </span>
          }
        />
        <CardBody>
          <ul className="mb-4 divide-y divide-border">
            {faqs.length === 0 && (
              <li className="py-2 text-sm text-muted-foreground">No FAQs yet.</li>
            )}
            {faqs.map((f) => (
              <li key={f.id} className="py-2.5 text-sm">
                <span className="font-medium text-foreground">{f.category}</span>
                <span className="text-muted-foreground">: {f.answer_en}</span>
              </li>
            ))}
          </ul>
          <AddFaq onAdded={loadAll} />
        </CardBody>
      </Card>

      {/* Sticky save bar */}
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

function AddService({ onAdded }) {
  const [name, setName] = useState("");
  const [duration, setDuration] = useState(30);
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/services", {
        method: "POST",
        body: { name, duration_min: Number(duration), price_display: price },
      });
      setName("");
      setPrice("");
      toast.success("Service added");
      onAdded();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={add} className="flex flex-wrap items-end gap-2">
      <Field label="Name" className="min-w-[160px] flex-1">
        <Input placeholder="Cleaning" value={name} onChange={(e) => setName(e.target.value)} required />
      </Field>
      <Field label="Minutes" className="w-24">
        <Input type="number" value={duration} onChange={(e) => setDuration(e.target.value)} />
      </Field>
      <Field label="Price" className="w-32">
        <Input placeholder="from $X" value={price} onChange={(e) => setPrice(e.target.value)} />
      </Field>
      <Button type="submit" icon={Plus} loading={busy}>
        Add
      </Button>
    </form>
  );
}

function AddRule({ onAdded }) {
  const [weekday, setWeekday] = useState(0);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("17:00");
  const [busy, setBusy] = useState(false);

  async function add(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/schedule-rules", {
        method: "POST",
        body: { weekday: Number(weekday), start_time: start, end_time: end },
      });
      toast.success("Hours added");
      onAdded();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={add} className="flex flex-wrap items-end gap-2">
      <Field label="Day" className="w-28">
        <Select value={weekday} onChange={(e) => setWeekday(e.target.value)}>
          {WEEKDAYS.map((d, i) => (
            <option key={i} value={i}>
              {d}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="From" className="w-32">
        <Input type="time" value={start} onChange={(e) => setStart(e.target.value)} />
      </Field>
      <Field label="To" className="w-32">
        <Input type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
      </Field>
      <Button type="submit" icon={Plus} loading={busy}>
        Add
      </Button>
    </form>
  );
}

function AddFaq({ onAdded }) {
  const [category, setCategory] = useState("");
  const [patterns, setPatterns] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/faqs", {
        method: "POST",
        body: { category, question_patterns: patterns, answer_en: answer },
      });
      setCategory("");
      setPatterns("");
      setAnswer("");
      toast.success("FAQ added");
      onAdded();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={add} className="grid gap-2 sm:grid-cols-3">
      <Field label="Category">
        <Input placeholder="parking" value={category} onChange={(e) => setCategory(e.target.value)} required />
      </Field>
      <Field label="Keywords">
        <Input placeholder="park, garage" value={patterns} onChange={(e) => setPatterns(e.target.value)} />
      </Field>
      <Field label="Answer">
        <Input placeholder="Free lot behind the building." value={answer} onChange={(e) => setAnswer(e.target.value)} required />
      </Field>
      <div className="sm:col-span-3">
        <Button type="submit" icon={Plus} loading={busy}>
          Add FAQ
        </Button>
      </div>
    </form>
  );
}
