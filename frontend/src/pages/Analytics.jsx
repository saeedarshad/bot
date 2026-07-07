import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import {
  TrendingUp,
  CalendarCheck,
  UserX,
  Bot,
  Timer,
  FileText,
  ChevronDown,
} from "lucide-react";
import { api } from "../api.js";
import { useAuth } from "../lib/auth.jsx";
import { useChartColors } from "../lib/useChartColors.js";
import {
  Card,
  CardHeader,
  StatCard,
  AnimatedNumber,
  Badge,
  EmptyState,
  Skeleton,
  Input,
} from "../components/ui/index.js";
import { fmtMoney, pct, fmtDuration, monthName } from "../lib/format.js";

const SOURCE_LABELS = { bot: "AI receptionist", dashboard: "Staff", walk_in: "Walk-in" };
const SOURCE_TONE = { bot: "bg-primary", dashboard: "bg-accent", walk_in: "bg-warning" };

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const b = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-md">
      <div className="font-medium text-foreground">{label}</div>
      <div className="mt-1 text-muted-foreground">
        {pct(b.rate)} · {b.no_show}/{b.decided} no-shows
      </div>
    </div>
  );
}

export default function Analytics() {
  const { me } = useAuth();
  const clinic = me?.clinic;
  const colors = useChartColors();

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
  const trend = useMemo(
    () =>
      (data?.no_show_trend || []).map((b) => ({
        ...b,
        pctRate: Math.round((b.rate || 0) * 1000) / 10,
        label: `${b.period.slice(5)}/${b.period.slice(2, 4)}`,
      })),
    [data]
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Analytics</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Bookings, no-shows, and revenue the AI recovered for you.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface p-1.5">
          <Input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="h-8 border-0 shadow-none focus:ring-0"
          />
          <span className="text-sm text-muted-foreground">→</span>
          <Input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="h-8 border-0 shadow-none focus:ring-0"
          />
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-danger/30 bg-danger/10 px-3.5 py-2.5 text-sm text-danger">
          {error}
        </div>
      )}

      {loading && !data ? (
        <div className="space-y-4">
          <Skeleton className="h-28 w-full rounded-2xl" />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-2xl" />
            ))}
          </div>
          <Skeleton className="h-64 w-full rounded-2xl" />
        </div>
      ) : data ? (
        <>
          {/* Headline: recovered revenue */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35 }}
            className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-primary via-indigo-600 to-accent p-6 text-white shadow-md"
          >
            <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
            <div className="relative">
              <div className="flex items-center gap-2 text-sm font-medium text-white/85">
                <TrendingUp className="h-4 w-4" />
                Recovered revenue
              </div>
              <div className="mt-1 text-4xl font-bold tabular-nums">
                <AnimatedNumber
                  value={Number(data.recovered.revenue) || 0}
                  format={(n) => fmtMoney(currency, n)}
                />
              </div>
              <div className="mt-1.5 text-sm text-white/80">
                {data.recovered.count} appointment{data.recovered.count === 1 ? "" : "s"} rebooked
                after a no-show
                {data.waitlist.fills > 0 &&
                  ` · ${data.waitlist.fills} waitlist fill${
                    data.waitlist.fills === 1 ? "" : "s"
                  }`}
              </div>
            </div>
          </motion.div>

          {/* Stat cards */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard
              index={0}
              label="Bookings"
              icon={CalendarCheck}
              accent="primary"
              value={<AnimatedNumber value={bookings.total} format={(n) => Math.round(n)} />}
              sub={`${pct(bookings.bot_share)} via AI receptionist`}
            />
            <StatCard
              index={1}
              label="No-show rate"
              icon={UserX}
              accent="warning"
              value={
                <AnimatedNumber
                  value={(data.no_show.rate || 0) * 100}
                  format={(n) => `${Math.round(n * 10) / 10}%`}
                />
              }
              sub={`${data.no_show.no_show}/${data.no_show.decided} visits`}
            />
            <StatCard
              index={2}
              label="Bot containment"
              icon={Bot}
              accent="success"
              value={
                <AnimatedNumber
                  value={(data.containment.rate || 0) * 100}
                  format={(n) => `${Math.round(n * 10) / 10}%`}
                />
              }
              sub={`${data.containment.escalated} of ${data.containment.total_conversations} escalated`}
            />
            <StatCard
              index={3}
              label="Median response"
              icon={Timer}
              accent="info"
              value={fmtDuration(data.response_time.median_seconds)}
              sub={`${data.response_time.sample} conversations`}
            />
          </div>

          {/* Charts */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="No-show rate trend" subtitle="Monthly, over decided visits" />
              <div className="p-4">
                {trend.length ? (
                  <ResponsiveContainer width="100%" height={220}>
                    <AreaChart data={trend} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                      <defs>
                        <linearGradient id="nsGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={colors.warning} stopOpacity={0.35} />
                          <stop offset="100%" stopColor={colors.warning} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} vertical={false} />
                      <XAxis
                        dataKey="label"
                        tick={{ fontSize: 11, fill: colors.muted }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: colors.muted }}
                        axisLine={false}
                        tickLine={false}
                        width={40}
                        tickFormatter={(v) => `${v}%`}
                      />
                      <Tooltip content={<ChartTooltip />} />
                      <Area
                        type="monotone"
                        dataKey="pctRate"
                        stroke={colors.warning}
                        strokeWidth={2.5}
                        fill="url(#nsGrad)"
                        dot={{ r: 3, fill: colors.warning, strokeWidth: 0 }}
                        activeDot={{ r: 5 }}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">
                    No completed visits in this range yet.
                  </div>
                )}
              </div>
            </Card>

            <Card>
              <CardHeader title="Bookings by source" subtitle="Where appointments came from" />
              <div className="space-y-4 p-5">
                {topSources.length ? (
                  topSources.map((s, i) => {
                    const share = bookings.total ? s.count / bookings.total : 0;
                    return (
                      <div key={s.source}>
                        <div className="mb-1.5 flex justify-between text-sm">
                          <span className="font-medium text-foreground">
                            {SOURCE_LABELS[s.source] || s.source}
                          </span>
                          <span className="tabular-nums text-muted-foreground">
                            {s.count} · {pct(share)}
                          </span>
                        </div>
                        <div className="h-2.5 overflow-hidden rounded-full bg-muted">
                          <motion.div
                            initial={{ width: 0 }}
                            animate={{ width: `${share * 100}%` }}
                            transition={{ duration: 0.6, delay: i * 0.08, ease: "easeOut" }}
                            className={"h-full rounded-full " + (SOURCE_TONE[s.source] || "bg-primary")}
                          />
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <div className="py-10 text-center text-sm text-muted-foreground">
                    No bookings in this range yet.
                  </div>
                )}
              </div>
            </Card>
          </div>

          {/* Monthly reports */}
          <Card>
            <CardHeader title="Monthly reports" subtitle="Frozen snapshots, one per month" />
            <div className="p-3">
              {reports.length ? (
                <ul className="divide-y divide-border">
                  {reports.map((r) => {
                    const isOpen = openReport === r;
                    return (
                      <li key={`${r.year}-${r.month}`}>
                        <button
                          onClick={() => setOpenReport(isOpen ? null : r)}
                          className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-3 text-left transition-colors hover:bg-surface-hover"
                        >
                          <div className="flex items-center gap-3">
                            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                              <FileText className="h-4 w-4" />
                            </div>
                            <div>
                              <div className="text-sm font-medium text-foreground">
                                {monthName(r.year, r.month)}
                              </div>
                              <div className="text-xs text-muted-foreground">
                                {fmtMoney(currency, r.data?.recovered?.revenue)} recovered ·{" "}
                                {r.data?.bookings?.total ?? 0} bookings · {pct(r.data?.no_show?.rate)}{" "}
                                no-show
                              </div>
                            </div>
                          </div>
                          <ChevronDown
                            className={
                              "h-4 w-4 text-muted-foreground transition-transform " +
                              (isOpen ? "rotate-180" : "")
                            }
                          />
                        </button>
                        {isOpen && (
                          <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: "auto" }}
                            className="overflow-hidden px-2 pb-3"
                          >
                            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                              <ReportStat label="Bookings" value={r.data?.bookings?.total ?? 0} />
                              <ReportStat
                                label="No-show"
                                value={pct(r.data?.no_show?.rate)}
                              />
                              <ReportStat
                                label="Recovered"
                                value={fmtMoney(currency, r.data?.recovered?.revenue)}
                              />
                              <ReportStat
                                label="Containment"
                                value={pct(r.data?.containment?.rate)}
                              />
                            </div>
                          </motion.div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <div className="px-2 py-6 text-center text-sm text-muted-foreground">
                  No reports yet — the first is generated automatically at the start of next month.
                </div>
              )}
            </div>
          </Card>
        </>
      ) : (
        <EmptyState title="No analytics" description="Nothing to show for this range." />
      )}
    </div>
  );
}

function ReportStat({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  );
}
