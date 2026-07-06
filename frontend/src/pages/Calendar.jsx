import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

const STATUS_STYLES = {
  pending: "bg-amber-100 text-amber-800 border-amber-200",
  confirmed: "bg-emerald-100 text-emerald-800 border-emerald-200",
  completed: "bg-slate-100 text-slate-600 border-slate-200",
  cancelled: "bg-red-100 text-red-700 border-red-200",
  no_show: "bg-rose-100 text-rose-700 border-rose-200",
  rescheduled: "bg-indigo-100 text-indigo-700 border-indigo-200",
};

function dayKey(iso, tz) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso));
}

function timeLabel(iso, tz) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

function shiftDay(key, delta) {
  const d = new Date(key + "T12:00:00");
  d.setDate(d.getDate() + delta);
  return d.toISOString().slice(0, 10);
}

// Interpret a wall-clock day + time as being in the clinic's timezone and
// return the corresponding UTC ISO string. The naive Date constructor parses
// in the browser's local zone, which is wrong when it differs from the clinic.
function clinicWallTimeToUTC(day, time, tz) {
  const asUTC = new Date(`${day}T${time}:00Z`);
  const tzWall = new Date(asUTC.toLocaleString("en-US", { timeZone: tz }));
  const utcWall = new Date(asUTC.toLocaleString("en-US", { timeZone: "UTC" }));
  const offset = tzWall.getTime() - utcWall.getTime();
  return new Date(asUTC.getTime() - offset).toISOString();
}

export default function Calendar({ clinic }) {
  const tz = clinic?.timezone || "America/New_York";
  const [day, setDay] = useState(() => dayKey(new Date().toISOString(), tz));
  const [appts, setAppts] = useState([]);
  const [services, setServices] = useState([]);
  const [patients, setPatients] = useState([]);
  const [costs, setCosts] = useState(null);
  const [showForm, setShowForm] = useState(false);

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
  }

  useEffect(() => {
    load();
  }, []);

  const dayAppts = useMemo(
    () =>
      appts
        .filter((a) => dayKey(a.starts_at, tz) === day)
        .sort((x, y) => x.starts_at.localeCompare(y.starts_at)),
    [appts, day, tz]
  );

  const atRiskCount = useMemo(
    () => dayAppts.filter((a) => a.at_risk).length,
    [dayAppts]
  );

  async function setStatus(id, status) {
    await api(`/appointments/${id}`, { method: "PATCH", body: { status } });
    load();
  }

  // Lifecycle actions (no_show bumps the patient's no-show count; complete marks
  // attended). These go through the dedicated guarded endpoints, not a raw PATCH.
  async function lifecycle(id, action) {
    await api(`/appointments/${id}/${action}`, { method: "POST" });
    load();
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <button onClick={() => setDay(shiftDay(day, -1))} className="px-2 py-1 border rounded">
            ←
          </button>
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className="border rounded px-2 py-1"
          />
          <button onClick={() => setDay(shiftDay(day, 1))} className="px-2 py-1 border rounded">
            →
          </button>
          <button
            onClick={() => setDay(dayKey(new Date().toISOString(), tz))}
            className="text-sm text-indigo-600 ml-2"
          >
            Today
          </button>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="bg-indigo-600 text-white text-sm rounded px-3 py-1.5 hover:bg-indigo-700"
        >
          {showForm ? "Close" : "+ New appointment"}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4 text-sm">
        <span className="px-2.5 py-1 rounded-full bg-slate-100 text-slate-600">
          {dayAppts.length} appointment{dayAppts.length === 1 ? "" : "s"}
        </span>
        {atRiskCount > 0 && (
          <span className="px-2.5 py-1 rounded-full bg-amber-100 text-amber-800 border border-amber-200">
            {atRiskCount} at risk — unconfirmed after reminder
          </span>
        )}
        {costs && (
          <span
            className="px-2.5 py-1 rounded-full bg-slate-100 text-slate-600 ml-auto"
            title="Estimated outbound messaging spend, month to date"
          >
            Messaging this month: {costs.currency} {costs.total} ({costs.message_count} msgs)
          </span>
        )}
      </div>

      {showForm && (
        <NewAppointment
          services={services}
          patients={patients}
          defaultDay={day}
          tz={tz}
          onCreated={() => {
            setShowForm(false);
            load();
          }}
        />
      )}

      <div className="space-y-2">
        {dayAppts.length === 0 && (
          <div className="text-slate-400 text-sm py-8 text-center">
            No appointments on this day.
          </div>
        )}
        {dayAppts.map((a) => (
          <div
            key={a.id}
            className={
              "border rounded-lg p-3 flex items-center justify-between " +
              (STATUS_STYLES[a.status] || "") +
              (a.at_risk ? " ring-2 ring-amber-400" : "")
            }
          >
            <div>
              <div className="font-medium flex items-center gap-2">
                {timeLabel(a.starts_at, tz)} · {a.service_name}
                {a.at_risk && (
                  <span className="text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded bg-amber-500 text-white">
                    At risk
                  </span>
                )}
              </div>
              <div className="text-sm opacity-80">
                {a.patient_name || a.patient_phone} · {a.status}
                {a.source ? ` · ${a.source}` : ""}
                {a.patient_confirmed_at ? " · patient confirmed" : ""}
              </div>
            </div>
            {["pending", "confirmed"].includes(a.status) && (
              <div className="flex gap-1">
                <button onClick={() => lifecycle(a.id, "complete")} className="text-xs px-2 py-1 bg-white/70 rounded border">
                  Complete
                </button>
                <button onClick={() => lifecycle(a.id, "no_show")} className="text-xs px-2 py-1 bg-white/70 rounded border">
                  No-show
                </button>
                <button onClick={() => setStatus(a.id, "cancelled")} className="text-xs px-2 py-1 bg-white/70 rounded border">
                  Cancel
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function NewAppointment({ services, patients, defaultDay, tz, onCreated }) {
  const [patient, setPatient] = useState("");
  const [service, setService] = useState("");
  const [time, setTime] = useState("09:00");
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setError(null);
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
    }
  }

  return (
    <form onSubmit={submit} className="bg-white border rounded-lg p-4 mb-4 grid grid-cols-2 gap-3">
      {error && <div className="col-span-2 text-sm text-red-600">{error}</div>}
      <label className="text-sm">
        <span className="text-slate-500">Patient</span>
        <select className="mt-1 w-full border rounded px-2 py-1.5" value={patient} onChange={(e) => setPatient(e.target.value)} required>
          <option value="">Select…</option>
          {patients.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name || p.phone_e164}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="text-slate-500">Service</span>
        <select className="mt-1 w-full border rounded px-2 py-1.5" value={service} onChange={(e) => setService(e.target.value)} required>
          <option value="">Select…</option>
          {services.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.duration_min}m)
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="text-slate-500">Time ({defaultDay})</span>
        <input type="time" className="mt-1 w-full border rounded px-2 py-1.5" value={time} onChange={(e) => setTime(e.target.value)} />
      </label>
      <div className="flex items-end">
        <button className="bg-indigo-600 text-white rounded px-4 py-2 text-sm hover:bg-indigo-700">
          Add appointment
        </button>
      </div>
    </form>
  );
}
