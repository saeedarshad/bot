import { useEffect, useState } from "react";
import { api } from "../api.js";

const BLANK = {
  name: "",
  service: "",
  interval_days: 180,
  window_days: 7,
  template_name: "",
  message_override: "",
  is_active: true,
};

function fmtMoney(currency, amount) {
  const n = Number(amount || 0);
  return `${currency} ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function monthDay(iso) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
}

export default function Recalls({ clinic }) {
  const currency = clinic?.currency || "USD";
  const [rules, setRules] = useState([]);
  const [services, setServices] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [form, setForm] = useState(BLANK);
  const [showForm, setShowForm] = useState(false);
  const [preview, setPreview] = useState(null); // { ruleId, eligible, projected_cost, sample }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function load() {
    const [r, s, c] = await Promise.all([
      api("/recall-rules"),
      api("/services"),
      api("/recall-campaigns").catch(() => []),
    ]);
    setRules(r);
    setServices(s);
    setCampaigns(c || []);
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  const serviceName = (id) => services.find((s) => s.id === id)?.name || `#${id}`;

  async function createRule(e) {
    e.preventDefault();
    setError(null);
    try {
      await api("/recall-rules", {
        method: "POST",
        body: {
          ...form,
          service: Number(form.service),
          interval_days: Number(form.interval_days),
          window_days: Number(form.window_days),
        },
      });
      setForm(BLANK);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function doPreview(rule) {
    setError(null);
    setPreview({ ruleId: rule.id, loading: true });
    try {
      const p = await api(`/recall-rules/${rule.id}/preview`);
      setPreview({ ruleId: rule.id, ...p });
    } catch (e) {
      setPreview(null);
      setError(e.message);
    }
  }

  async function doRun(rule) {
    if (!preview || preview.ruleId !== rule.id) return;
    const ok = window.confirm(
      `Send this recall to ${preview.eligible} patient(s) for an estimated ${fmtMoney(
        currency,
        preview.projected_cost
      )}? This sends paid marketing messages.`
    );
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/recall-rules/${rule.id}/run`, { method: "POST" });
      setPreview(null);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(rule) {
    await api(`/recall-rules/${rule.id}`, {
      method: "PATCH",
      body: { is_active: !rule.is_active },
    });
    await load();
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-lg font-semibold">Recall campaigns</h1>
          <p className="text-sm text-slate-500">
            Bring patients back for their next visit. Recalls are paid marketing messages —
            you always preview the count and cost before sending.
          </p>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="bg-indigo-600 text-white text-sm rounded px-3 py-1.5 hover:bg-indigo-700"
        >
          {showForm ? "Close" : "+ New rule"}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded p-3 mb-4">
          {error}
        </div>
      )}

      {showForm && (
        <form onSubmit={createRule} className="bg-white border border-slate-200 rounded-lg p-4 mb-4 grid gap-3 md:grid-cols-2">
          <label className="text-sm">
            <span className="text-slate-500">Name</span>
            <input
              className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="6-month cleaning recall"
            />
          </label>
          <label className="text-sm">
            <span className="text-slate-500">Service</span>
            <select
              required
              className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
              value={form.service}
              onChange={(e) => setForm({ ...form, service: e.target.value })}
            >
              <option value="">Select a service…</option>
              {services.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-slate-500">Recall after (days)</span>
            <input
              type="number"
              min="1"
              required
              className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
              value={form.interval_days}
              onChange={(e) => setForm({ ...form, interval_days: e.target.value })}
            />
          </label>
          <label className="text-sm">
            <span className="text-slate-500">Window (± days)</span>
            <input
              type="number"
              min="0"
              className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
              value={form.window_days}
              onChange={(e) => setForm({ ...form, window_days: e.target.value })}
            />
          </label>
          <label className="text-sm">
            <span className="text-slate-500">Meta template name</span>
            <input
              required
              className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
              value={form.template_name}
              onChange={(e) => setForm({ ...form, template_name: e.target.value })}
              placeholder="recall_checkup"
            />
          </label>
          <label className="text-sm md:col-span-2">
            <span className="text-slate-500">Message override (fallback text; {"{name}"} / {"{clinic}"} allowed)</span>
            <textarea
              className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
              rows={2}
              value={form.message_override}
              onChange={(e) => setForm({ ...form, message_override: e.target.value })}
            />
          </label>
          <div className="md:col-span-2">
            <button className="bg-indigo-600 text-white text-sm rounded px-3 py-1.5 hover:bg-indigo-700">
              Save rule
            </button>
          </div>
        </form>
      )}

      <div className="space-y-3 mb-6">
        {rules.length === 0 && (
          <div className="text-sm text-slate-400">No recall rules yet.</div>
        )}
        {rules.map((rule) => (
          <div key={rule.id} className="bg-white border border-slate-200 rounded-lg p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="font-medium flex items-center gap-2">
                  {rule.name || `${rule.service_name} recall`}
                  {!rule.is_active && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">
                      inactive
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  {rule.service_name} · {rule.interval_days} days (±{rule.window_days}) · template{" "}
                  <code className="text-slate-600">{rule.template_name}</code>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => toggleActive(rule)}
                  className="text-xs text-slate-500 hover:text-slate-800"
                >
                  {rule.is_active ? "Deactivate" : "Activate"}
                </button>
                <button
                  onClick={() => doPreview(rule)}
                  className="text-sm border border-slate-300 rounded px-3 py-1 hover:bg-slate-50"
                >
                  Preview
                </button>
              </div>
            </div>

            {preview && preview.ruleId === rule.id && (
              <div className="mt-3 bg-slate-50 border border-slate-200 rounded p-3">
                {preview.loading ? (
                  <div className="text-sm text-slate-400">Checking eligibility…</div>
                ) : (
                  <div className="flex items-center justify-between gap-4 flex-wrap">
                    <div className="text-sm">
                      <span className="font-medium">{preview.eligible}</span> eligible ·
                      projected cost{" "}
                      <span className="font-medium">
                        {fmtMoney(currency, preview.projected_cost)}
                      </span>
                      {preview.sample?.length > 0 && (
                        <span className="text-slate-400"> · e.g. {preview.sample.join(", ")}</span>
                      )}
                    </div>
                    <button
                      disabled={busy || preview.eligible === 0}
                      onClick={() => doRun(rule)}
                      className="bg-emerald-600 text-white text-sm rounded px-3 py-1.5 hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {busy ? "Sending…" : `Send to ${preview.eligible}`}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="bg-white border border-slate-200 rounded-lg p-4">
        <div className="text-sm font-medium mb-3">Campaign history</div>
        {campaigns.length === 0 ? (
          <div className="text-sm text-slate-400">No campaigns run yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-400 border-b border-slate-100">
                <th className="py-1.5">Date</th>
                <th>Rule</th>
                <th>Status</th>
                <th className="text-right">Eligible</th>
                <th className="text-right">Sent</th>
                <th className="text-right">Skipped</th>
                <th className="text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.id} className="border-b border-slate-50">
                  <td className="py-1.5">{monthDay(c.created_at)}</td>
                  <td>{c.service_name}</td>
                  <td>
                    <span
                      className={
                        "text-xs px-2 py-0.5 rounded-full " +
                        (c.status === "completed"
                          ? "bg-emerald-100 text-emerald-700"
                          : c.status === "running"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-slate-100 text-slate-500")
                      }
                    >
                      {c.status}
                    </span>
                  </td>
                  <td className="text-right">{c.eligible}</td>
                  <td className="text-right">{c.sent}</td>
                  <td className="text-right">{c.skipped}</td>
                  <td className="text-right">{fmtMoney(currency, c.actual_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
