import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

function fmtMoney(currency, amount) {
  const n = Number(amount || 0);
  return `${currency} ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(rate) {
  return `${Math.round((rate || 0) * 1000) / 10}%`;
}

function fmtDuration(seconds) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

function monthName(year, month) {
  return new Date(year, month - 1, 1).toLocaleString(undefined, {
    month: "long",
    year: "numeric",
  });
}

function Stat({ label, value, sub, accent }) {
  return (
    <div className="bg-white rounded-lg border border-slate-200 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={"text-2xl font-semibold mt-1 " + (accent || "text-slate-800")}>
        {value}
      </div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

function TrendBars({ trend }) {
  if (!trend?.length) {
    return <div className="text-sm text-slate-400">No completed visits in this range yet.</div>;
  }
  const max = Math.max(...trend.map((b) => b.rate), 0.01);
  return (
    <div className="flex items-end gap-3 h-32">
      {trend.map((b) => (
        <div key={b.period} className="flex flex-col items-center flex-1 min-w-0">
          <div className="text-xs text-slate-500 mb-1">{pct(b.rate)}</div>
          <div className="w-full bg-slate-100 rounded-t flex items-end" style={{ height: "100%" }}>
            <div
              className="w-full bg-amber-400 rounded-t"
              style={{ height: `${(b.rate / max) * 100}%`, minHeight: b.decided ? "2px" : "0" }}
              title={`${b.no_show}/${b.decided} no-shows`}
            />
          </div>
          <div className="text-[11px] text-slate-400 mt-1 truncate w-full text-center">
            {b.period.slice(5)}/{b.period.slice(2, 4)}
          </div>
        </div>
      ))}
    </div>
  );
}

const SOURCE_LABELS = { bot: "AI receptionist", dashboard: "Staff", walk_in: "Walk-in" };

export default function Analytics({ clinic }) {
  const today = new Date();
  const firstOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
  const iso = (d) => d.toISOString().slice(0, 10);

  const [from, setFrom] = useState(iso(firstOfMonth));
  const [to, setTo] = useState(iso(today));
  const [data, setData] = useState(null);
  const [reports, setReports] = useState([]);
  const [openReport, setOpenReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [a, r] = await Promise.all([
        api(`/analytics?from=${from}&to=${to}`),
        api("/reports/monthly").catch(() => []),
      ]);
      setData(a);
      setReports(r || []);
    } catch (e) {
      setError(e.message || "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to]);

  const currency = clinic?.currency || data?.currency || "USD";
  const bookings = data?.bookings;
  const topSources = useMemo(
    () => (bookings?.by_source || []).filter((s) => s.count > 0),
    [bookings]
  );

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
        <div>
          <h1 className="text-lg font-semibold">Analytics</h1>
          <p className="text-sm text-slate-500">Bookings, no-shows, and recovered revenue.</p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <label className="text-slate-500">From</label>
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="border border-slate-300 rounded px-2 py-1"
          />
          <label className="text-slate-500">To</label>
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="border border-slate-300 rounded px-2 py-1"
          />
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded p-3 mb-4">
          {error}
        </div>
      )}
      {loading && !data ? (
        <div className="text-slate-400 text-sm">Loading…</div>
      ) : data ? (
        <>
          {/* Headline: recovered revenue */}
          <div className="bg-gradient-to-br from-emerald-500 to-emerald-600 text-white rounded-lg p-5 mb-4">
            <div className="text-xs uppercase tracking-wide opacity-80">
              Recovered revenue (no-show rebookings)
            </div>
            <div className="text-3xl font-bold mt-1">
              {fmtMoney(currency, data.recovered.revenue)}
            </div>
            <div className="text-sm opacity-90 mt-1">
              {data.recovered.count} appointment{data.recovered.count === 1 ? "" : "s"} rebooked after a no-show
              {data.waitlist.fills > 0 &&
                ` · ${data.waitlist.fills} waitlist fill${data.waitlist.fills === 1 ? "" : "s"}`}
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <Stat
              label="Bookings"
              value={bookings.total}
              sub={`${pct(bookings.bot_share)} via AI receptionist`}
            />
            <Stat
              label="No-show rate"
              value={pct(data.no_show.rate)}
              sub={`${data.no_show.no_show}/${data.no_show.decided} visits`}
              accent="text-amber-600"
            />
            <Stat
              label="Bot containment"
              value={pct(data.containment.rate)}
              sub={`${data.containment.escalated} of ${data.containment.total_conversations} escalated`}
            />
            <Stat
              label="Median response"
              value={fmtDuration(data.response_time.median_seconds)}
              sub={`${data.response_time.sample} conversations`}
            />
          </div>

          <div className="grid md:grid-cols-2 gap-4 mb-4">
            <div className="bg-white rounded-lg border border-slate-200 p-4">
              <div className="text-sm font-medium mb-3">No-show rate trend</div>
              <TrendBars trend={data.no_show_trend} />
            </div>
            <div className="bg-white rounded-lg border border-slate-200 p-4">
              <div className="text-sm font-medium mb-3">Bookings by source</div>
              {topSources.length ? (
                <div className="space-y-2">
                  {topSources.map((s) => {
                    const share = bookings.total ? s.count / bookings.total : 0;
                    return (
                      <div key={s.source}>
                        <div className="flex justify-between text-xs text-slate-500 mb-0.5">
                          <span>{SOURCE_LABELS[s.source] || s.source}</span>
                          <span>{s.count}</span>
                        </div>
                        <div className="h-2 bg-slate-100 rounded-full">
                          <div
                            className="h-2 bg-indigo-500 rounded-full"
                            style={{ width: `${share * 100}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-sm text-slate-400">No bookings in this range yet.</div>
              )}
            </div>
          </div>

          {/* Monthly reports */}
          <div className="bg-white rounded-lg border border-slate-200 p-4">
            <div className="text-sm font-medium mb-3">Monthly reports</div>
            {reports.length ? (
              <div className="divide-y divide-slate-100">
                {reports.map((r) => (
                  <div
                    key={`${r.year}-${r.month}`}
                    className="flex items-center justify-between py-2"
                  >
                    <div>
                      <div className="text-sm font-medium">{monthName(r.year, r.month)}</div>
                      <div className="text-xs text-slate-400">
                        {fmtMoney(currency, r.data?.recovered?.revenue)} recovered ·{" "}
                        {r.data?.bookings?.total ?? 0} bookings ·{" "}
                        {pct(r.data?.no_show?.rate)} no-show
                      </div>
                    </div>
                    <button
                      onClick={() => setOpenReport(openReport === r ? null : r)}
                      className="text-sm text-indigo-600 hover:text-indigo-800"
                    >
                      {openReport === r ? "Hide" : "View"}
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-sm text-slate-400">
                No reports yet — the first is generated automatically at the start of next month.
              </div>
            )}
            {openReport && (
              <pre className="mt-3 bg-slate-50 border border-slate-200 rounded p-3 text-xs overflow-auto max-h-80">
                {JSON.stringify(openReport.data, null, 2)}
              </pre>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
