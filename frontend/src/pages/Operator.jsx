import { useEffect, useState } from "react";
import { api } from "../api.js";

const BLANK_CLINIC = {
  name: "",
  timezone: "America/New_York",
  currency: "USD",
  whatsapp_phone_number_id: "",
  plan: "demo",
  staff_username: "",
  staff_password: "",
};

const STATUS_STYLES = {
  active: "bg-emerald-100 text-emerald-700",
  suspended: "bg-red-100 text-red-700",
  cancelled: "bg-slate-200 text-slate-600",
};

function StatusPill({ status }) {
  return (
    <span
      className={
        "text-xs px-2 py-0.5 rounded-full " +
        (STATUS_STYLES[status] || "bg-slate-100 text-slate-500")
      }
    >
      {status || "—"}
    </span>
  );
}

function ClinicRow({ clinic, onChanged, onError }) {
  const [open, setOpen] = useState(false);
  const sub = clinic.subscription || {};
  const [form, setForm] = useState({
    plan: sub.plan || "demo",
    status: sub.status || "active",
    paid_through: sub.paid_through || "",
    notes: sub.notes || "",
  });
  const [staff, setStaff] = useState(null);
  const [newStaff, setNewStaff] = useState({ username: "", password: "" });
  const [busy, setBusy] = useState(false);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && staff === null) {
      try {
        setStaff(await api(`/admin/clinics/${clinic.id}/staff`));
      } catch (e) {
        onError(e.message);
      }
    }
  }

  async function saveSubscription(e) {
    e.preventDefault();
    setBusy(true);
    onError(null);
    try {
      await api(`/admin/clinics/${clinic.id}/subscription`, {
        method: "PATCH",
        body: {
          plan: form.plan,
          status: form.status,
          paid_through: form.paid_through || null,
          notes: form.notes,
        },
      });
      await onChanged();
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function addStaff(e) {
    e.preventDefault();
    setBusy(true);
    onError(null);
    try {
      const list = await api(`/admin/clinics/${clinic.id}/staff`, {
        method: "POST",
        body: newStaff,
      });
      setStaff(list);
      setNewStaff({ username: "", password: "" });
      await onChanged();
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (
      !window.confirm(
        `Delete "${clinic.name}"? This permanently removes the clinic and ALL its ` +
          `patients, appointments, and messages. This cannot be undone.`
      )
    )
      return;
    setBusy(true);
    onError(null);
    try {
      await api(`/admin/clinics/${clinic.id}`, { method: "DELETE" });
      await onChanged();
    } catch (e) {
      onError(e.message);
      setBusy(false);
    }
  }

  return (
    <>
      <tr className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer" onClick={toggle}>
        <td className="py-2">
          <div className="font-medium">{clinic.name}</div>
          <div className="text-xs text-slate-400">{clinic.slug}</div>
        </td>
        <td className="text-slate-500">{clinic.timezone}</td>
        <td>{sub.plan || "—"}</td>
        <td>
          <StatusPill status={sub.status} />
        </td>
        <td className="text-slate-500">{sub.paid_through || "—"}</td>
        <td className="text-right text-slate-500">{clinic.staff_count}</td>
        <td className="text-right text-slate-500">{clinic.patient_count}</td>
        <td className="text-right text-xs text-indigo-600">{open ? "▲" : "manage"}</td>
      </tr>
      {open && (
        <tr className="bg-slate-50 border-b border-slate-100">
          <td colSpan={8} className="p-4">
            <div className="grid md:grid-cols-2 gap-6">
              <form onSubmit={saveSubscription} className="space-y-3">
                <div className="text-sm font-medium">Subscription</div>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-sm">
                    <span className="text-slate-500">Status</span>
                    <select
                      className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                      value={form.status}
                      onChange={(e) => setForm({ ...form, status: e.target.value })}
                    >
                      <option value="active">active</option>
                      <option value="suspended">suspended</option>
                      <option value="cancelled">cancelled</option>
                    </select>
                  </label>
                  <label className="text-sm">
                    <span className="text-slate-500">Plan</span>
                    <input
                      className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                      value={form.plan}
                      onChange={(e) => setForm({ ...form, plan: e.target.value })}
                    />
                  </label>
                  <label className="text-sm">
                    <span className="text-slate-500">Paid through</span>
                    <input
                      type="date"
                      className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                      value={form.paid_through || ""}
                      onChange={(e) => setForm({ ...form, paid_through: e.target.value })}
                    />
                  </label>
                </div>
                <label className="text-sm block">
                  <span className="text-slate-500">Notes</span>
                  <textarea
                    rows={2}
                    className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                    value={form.notes}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  />
                </label>
                <button
                  disabled={busy}
                  className="bg-indigo-600 text-white text-sm rounded px-3 py-1.5 hover:bg-indigo-700 disabled:opacity-50"
                >
                  Save subscription
                </button>
              </form>

              <div className="space-y-3">
                <div className="text-sm font-medium">Staff logins</div>
                <ul className="text-sm space-y-1">
                  {(staff || []).map((s) => (
                    <li key={s.id} className="flex items-center gap-2">
                      <span>{s.username}</span>
                      {!s.is_active && (
                        <span className="text-xs text-slate-400">(disabled)</span>
                      )}
                    </li>
                  ))}
                  {staff && staff.length === 0 && (
                    <li className="text-slate-400">No staff logins yet.</li>
                  )}
                </ul>
                <form onSubmit={addStaff} className="flex flex-wrap items-end gap-2">
                  <label className="text-sm">
                    <span className="text-slate-500">Username</span>
                    <input
                      className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                      value={newStaff.username}
                      onChange={(e) => setNewStaff({ ...newStaff, username: e.target.value })}
                    />
                  </label>
                  <label className="text-sm">
                    <span className="text-slate-500">Password (8+)</span>
                    <input
                      type="password"
                      className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                      value={newStaff.password}
                      onChange={(e) => setNewStaff({ ...newStaff, password: e.target.value })}
                    />
                  </label>
                  <button
                    disabled={busy}
                    className="border border-slate-300 rounded px-3 py-1.5 text-sm hover:bg-white disabled:opacity-50"
                  >
                    Add staff
                  </button>
                </form>

                <div className="pt-3 border-t border-slate-200">
                  <button
                    disabled={busy}
                    onClick={remove}
                    className="text-sm text-red-600 hover:text-red-800 disabled:opacity-50"
                  >
                    Delete clinic
                  </button>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function Operator({ me, onLogout }) {
  const [clinics, setClinics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK_CLINIC);
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setClinics(await api("/admin/clinics"));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createClinic(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/admin/clinics", { method: "POST", body: form });
      setForm(BLANK_CLINIC);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div>
            <div className="font-semibold">Receptionaly — Operator console</div>
            <div className="text-xs text-slate-400">Platform administration</div>
          </div>
          <button onClick={onLogout} className="text-sm text-slate-500 hover:text-slate-800">
            Sign out ({me.username})
          </button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-lg font-semibold">Clinics</h1>
            <p className="text-sm text-slate-500">
              Add or remove clinics and set each one's pay status. Suspending a
              clinic cuts off its dashboard and its bot.
            </p>
          </div>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="bg-indigo-600 text-white text-sm rounded px-3 py-1.5 hover:bg-indigo-700"
          >
            {showForm ? "Close" : "+ New clinic"}
          </button>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded p-3 mb-4">
            {error}
          </div>
        )}

        {showForm && (
          <form
            onSubmit={createClinic}
            className="bg-white border border-slate-200 rounded-lg p-4 mb-4 grid gap-3 md:grid-cols-2"
          >
            <label className="text-sm">
              <span className="text-slate-500">Clinic name</span>
              <input
                required
                className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Bright Smiles Dental"
              />
            </label>
            <label className="text-sm">
              <span className="text-slate-500">Timezone</span>
              <input
                className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={form.timezone}
                onChange={(e) => setForm({ ...form, timezone: e.target.value })}
              />
            </label>
            <label className="text-sm">
              <span className="text-slate-500">Currency</span>
              <input
                className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
              />
            </label>
            <label className="text-sm">
              <span className="text-slate-500">WhatsApp phone_number_id (optional)</span>
              <input
                className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={form.whatsapp_phone_number_id}
                onChange={(e) =>
                  setForm({ ...form, whatsapp_phone_number_id: e.target.value })
                }
              />
            </label>
            <label className="text-sm">
              <span className="text-slate-500">Plan</span>
              <input
                className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={form.plan}
                onChange={(e) => setForm({ ...form, plan: e.target.value })}
              />
            </label>
            <div className="md:col-span-2 border-t border-slate-100 pt-3 text-xs text-slate-400">
              First staff login (optional — you can add staff later)
            </div>
            <label className="text-sm">
              <span className="text-slate-500">Staff username</span>
              <input
                className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={form.staff_username}
                onChange={(e) => setForm({ ...form, staff_username: e.target.value })}
              />
            </label>
            <label className="text-sm">
              <span className="text-slate-500">Staff password (8+)</span>
              <input
                type="password"
                className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={form.staff_password}
                onChange={(e) => setForm({ ...form, staff_password: e.target.value })}
              />
            </label>
            <div className="md:col-span-2">
              <button
                disabled={busy}
                className="bg-indigo-600 text-white text-sm rounded px-3 py-1.5 hover:bg-indigo-700 disabled:opacity-50"
              >
                {busy ? "Creating…" : "Create clinic"}
              </button>
            </div>
          </form>
        )}

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          {loading ? (
            <div className="text-sm text-slate-400">Loading…</div>
          ) : clinics.length === 0 ? (
            <div className="text-sm text-slate-400">No clinics yet.</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-400 border-b border-slate-100">
                  <th className="py-1.5">Clinic</th>
                  <th>Timezone</th>
                  <th>Plan</th>
                  <th>Status</th>
                  <th>Paid through</th>
                  <th className="text-right">Staff</th>
                  <th className="text-right">Patients</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {clinics.map((c) => (
                  <ClinicRow
                    key={c.id}
                    clinic={c}
                    onChanged={load}
                    onError={setError}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>
    </div>
  );
}
