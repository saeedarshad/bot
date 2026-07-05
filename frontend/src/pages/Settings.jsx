import { useEffect, useState } from "react";
import { api } from "../api.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CLINIC_FIELDS = [
  ["emergency_phone", "Emergency phone"],
  ["phone_display", "Display phone"],
  ["address", "Address"],
  ["maps_link", "Maps link"],
  ["cancellation_policy", "Cancellation policy"],
  ["new_patient_form_url", "New-patient form URL"],
  ["booking_horizon_days", "Booking horizon (days)"],
  ["min_notice_minutes", "Min notice (minutes)"],
  ["slot_granularity_minutes", "Slot granularity (minutes)"],
];

function Section({ title, children }) {
  return (
    <section className="bg-white border rounded-lg p-4 mb-4">
      <h2 className="font-semibold mb-3">{title}</h2>
      {children}
    </section>
  );
}

export default function Settings() {
  const [clinic, setClinic] = useState(null);
  const [services, setServices] = useState([]);
  const [rules, setRules] = useState([]);
  const [faqs, setFaqs] = useState([]);
  const [saved, setSaved] = useState(false);

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

  async function saveClinic(e) {
    e.preventDefault();
    const updated = await api("/settings", { method: "PATCH", body: clinic });
    setClinic(updated);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  if (!clinic) return <div className="text-slate-400 text-sm">Loading…</div>;

  return (
    <div>
      <Section title="Clinic details">
        <form onSubmit={saveClinic} className="grid grid-cols-2 gap-3">
          {CLINIC_FIELDS.map(([key, label]) => (
            <label key={key} className="text-sm">
              <span className="text-slate-500">{label}</span>
              <input
                className="mt-1 w-full border rounded px-2 py-1.5"
                value={clinic[key] ?? ""}
                onChange={(e) => setClinic({ ...clinic, [key]: e.target.value })}
              />
            </label>
          ))}
          <div className="col-span-2 flex items-center gap-3">
            <button className="bg-indigo-600 text-white rounded px-4 py-2 text-sm hover:bg-indigo-700">
              Save
            </button>
            {saved && <span className="text-sm text-emerald-600">Saved</span>}
          </div>
        </form>
      </Section>

      <Section title="Services">
        <ul className="mb-3 divide-y">
          {services.map((s) => (
            <li key={s.id} className="py-2 flex justify-between text-sm">
              <span>
                {s.name} · {s.duration_min}m {s.price_display && `· ${s.price_display}`}
              </span>
              <span className={s.is_active ? "text-emerald-600" : "text-slate-400"}>
                {s.is_active ? "active" : "inactive"}
              </span>
            </li>
          ))}
        </ul>
        <AddService onAdded={loadAll} />
      </Section>

      <Section title="Working hours">
        <ul className="mb-3 divide-y">
          {rules.map((r) => (
            <li key={r.id} className="py-2 text-sm">
              {WEEKDAYS[r.weekday]}: {r.start_time}–{r.end_time}
            </li>
          ))}
        </ul>
        <AddRule onAdded={loadAll} />
      </Section>

      <Section title="FAQ answers">
        <ul className="mb-3 divide-y">
          {faqs.map((f) => (
            <li key={f.id} className="py-2 text-sm">
              <span className="font-medium">{f.category}</span>: {f.answer_en}
            </li>
          ))}
        </ul>
        <AddFaq onAdded={loadAll} />
      </Section>
    </div>
  );
}

function AddService({ onAdded }) {
  const [name, setName] = useState("");
  const [duration, setDuration] = useState(30);
  const [price, setPrice] = useState("");
  async function add(e) {
    e.preventDefault();
    await api("/services", {
      method: "POST",
      body: { name, duration_min: Number(duration), price_display: price },
    });
    setName("");
    setPrice("");
    onAdded();
  }
  return (
    <form onSubmit={add} className="flex gap-2 text-sm">
      <input className="border rounded px-2 py-1 flex-1" placeholder="Service name" value={name} onChange={(e) => setName(e.target.value)} required />
      <input className="border rounded px-2 py-1 w-20" type="number" value={duration} onChange={(e) => setDuration(e.target.value)} />
      <input className="border rounded px-2 py-1 w-28" placeholder="from $X" value={price} onChange={(e) => setPrice(e.target.value)} />
      <button className="bg-slate-800 text-white rounded px-3">Add</button>
    </form>
  );
}

function AddRule({ onAdded }) {
  const [weekday, setWeekday] = useState(0);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("17:00");
  async function add(e) {
    e.preventDefault();
    await api("/schedule-rules", {
      method: "POST",
      body: { weekday: Number(weekday), start_time: start, end_time: end },
    });
    onAdded();
  }
  return (
    <form onSubmit={add} className="flex gap-2 text-sm">
      <select className="border rounded px-2 py-1" value={weekday} onChange={(e) => setWeekday(e.target.value)}>
        {WEEKDAYS.map((d, i) => (
          <option key={i} value={i}>{d}</option>
        ))}
      </select>
      <input type="time" className="border rounded px-2 py-1" value={start} onChange={(e) => setStart(e.target.value)} />
      <input type="time" className="border rounded px-2 py-1" value={end} onChange={(e) => setEnd(e.target.value)} />
      <button className="bg-slate-800 text-white rounded px-3">Add</button>
    </form>
  );
}

function AddFaq({ onAdded }) {
  const [category, setCategory] = useState("");
  const [patterns, setPatterns] = useState("");
  const [answer, setAnswer] = useState("");
  async function add(e) {
    e.preventDefault();
    await api("/faqs", {
      method: "POST",
      body: { category, question_patterns: patterns, answer_en: answer },
    });
    setCategory("");
    setPatterns("");
    setAnswer("");
    onAdded();
  }
  return (
    <form onSubmit={add} className="grid grid-cols-3 gap-2 text-sm">
      <input className="border rounded px-2 py-1" placeholder="category" value={category} onChange={(e) => setCategory(e.target.value)} required />
      <input className="border rounded px-2 py-1" placeholder="keywords" value={patterns} onChange={(e) => setPatterns(e.target.value)} />
      <input className="border rounded px-2 py-1" placeholder="answer" value={answer} onChange={(e) => setAnswer(e.target.value)} required />
      <button className="bg-slate-800 text-white rounded px-3 col-span-3 justify-self-start py-1">Add FAQ</button>
    </form>
  );
}
