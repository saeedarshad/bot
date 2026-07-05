import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Escalations() {
  const [tickets, setTickets] = useState([]);

  async function load() {
    setTickets(await api("/escalations?status=open"));
  }

  useEffect(() => {
    load();
  }, []);

  async function resolve(id) {
    await api(`/escalations/${id}/resolve`, { method: "POST" });
    load();
  }

  return (
    <div className="space-y-2">
      <p className="text-sm text-slate-400 mb-2">
        Open handoffs — resolving one resumes the bot on that conversation.
      </p>
      {tickets.length === 0 && (
        <div className="text-slate-400 text-sm py-8 text-center">No open escalations.</div>
      )}
      {tickets.map((t) => (
        <div key={t.id} className="bg-white border rounded-lg p-3 flex items-center justify-between">
          <div>
            <div className="font-medium">{t.patient_name || t.patient_phone}</div>
            <div className="text-sm text-slate-500">
              {t.reason || "No reason given"} · {new Date(t.created_at).toLocaleString()}
            </div>
          </div>
          <button
            onClick={() => resolve(t.id)}
            className="bg-emerald-600 text-white text-sm rounded px-3 py-1.5 hover:bg-emerald-700"
          >
            Resolve & resume bot
          </button>
        </div>
      ))}
    </div>
  );
}
