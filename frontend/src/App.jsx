import { useEffect, useState } from "react";
import { api, ensureCsrf } from "./api.js";
import Login from "./pages/Login.jsx";
import Calendar from "./pages/Calendar.jsx";
import Patients from "./pages/Patients.jsx";
import Escalations from "./pages/Escalations.jsx";
import Settings from "./pages/Settings.jsx";
import Chat from "./pages/Chat.jsx";
import Analytics from "./pages/Analytics.jsx";
import Recalls from "./pages/Recalls.jsx";

const TABS = [
  ["calendar", "Calendar"],
  ["analytics", "Analytics"],
  ["recalls", "Recalls"],
  ["chat", "Chat (test)"],
  ["patients", "Patients"],
  ["escalations", "Escalations"],
  ["settings", "Settings"],
];

export default function App() {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("calendar");

  async function loadMe() {
    try {
      const data = await api("/me");
      setMe(data);
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    ensureCsrf().then(loadMe);
  }, []);

  async function logout() {
    await api("/auth/logout", { method: "POST" });
    setMe(null);
  }

  if (loading) return <div className="p-8 text-slate-500">Loading…</div>;
  if (!me) return <Login onLoggedIn={loadMe} />;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div>
            <div className="font-semibold">{me.clinic?.name}</div>
            <div className="text-xs text-slate-400">Receptionaly staff dashboard</div>
          </div>
          <button onClick={logout} className="text-sm text-slate-500 hover:text-slate-800">
            Sign out ({me.username})
          </button>
        </div>
        <nav className="max-w-5xl mx-auto px-4 flex gap-1">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={
                "px-4 py-2 text-sm border-b-2 -mb-px " +
                (tab === key
                  ? "border-indigo-600 text-indigo-700 font-medium"
                  : "border-transparent text-slate-500 hover:text-slate-800")
              }
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6">
        {tab === "calendar" && <Calendar clinic={me.clinic} />}
        {tab === "analytics" && <Analytics clinic={me.clinic} />}
        {tab === "recalls" && <Recalls clinic={me.clinic} />}
        {tab === "chat" && <Chat />}
        {tab === "patients" && <Patients />}
        {tab === "escalations" && <Escalations />}
        {tab === "settings" && <Settings />}
      </main>
    </div>
  );
}
