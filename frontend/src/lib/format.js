// Shared formatters used across pages. Keeping these in one place means the
// dashboard is consistent about money, percentages, and clinic-local times.

export function fmtMoney(currency, amount) {
  const n = Number(amount || 0);
  return `${currency} ${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function pct(rate) {
  return `${Math.round((rate || 0) * 1000) / 10}%`;
}

export function fmtDuration(seconds) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

export function monthName(year, month) {
  return new Date(year, month - 1, 1).toLocaleString(undefined, {
    month: "long",
    year: "numeric",
  });
}

export function monthDay(iso) {
  return iso
    ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" })
    : "";
}

// --- clinic-timezone aware helpers (moved out of Calendar so pages share them) ---

export function dayKey(iso, tz) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso));
}

export function timeLabel(iso, tz) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function shiftDay(key, delta) {
  const d = new Date(key + "T12:00:00");
  d.setDate(d.getDate() + delta);
  return d.toISOString().slice(0, 10);
}

// Interpret a wall-clock day + time as being in the clinic's timezone and return
// the corresponding UTC ISO string. The naive Date constructor parses in the
// browser's local zone, which is wrong when it differs from the clinic.
export function clinicWallTimeToUTC(day, time, tz) {
  const asUTC = new Date(`${day}T${time}:00Z`);
  const tzWall = new Date(asUTC.toLocaleString("en-US", { timeZone: tz }));
  const utcWall = new Date(asUTC.toLocaleString("en-US", { timeZone: "UTC" }));
  const offset = tzWall.getTime() - utcWall.getTime();
  return new Date(asUTC.getTime() - offset).toISOString();
}

export function relativeDay(key, tz) {
  const todayKey = dayKey(new Date().toISOString(), tz);
  if (key === todayKey) return "Today";
  if (key === shiftDay(todayKey, -1)) return "Yesterday";
  if (key === shiftDay(todayKey, 1)) return "Tomorrow";
  return new Date(key + "T12:00:00").toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}
