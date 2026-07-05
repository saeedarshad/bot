import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Patients() {
  const [patients, setPatients] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    api("/patients").then(setPatients);
  }, []);

  async function open(p) {
    setSelected(p);
    setMessages(await api(`/patients/${p.id}/messages`));
  }

  return (
    <div className="grid grid-cols-3 gap-4">
      <div className="col-span-1 bg-white border rounded-lg divide-y">
        {patients.length === 0 && (
          <div className="p-4 text-sm text-slate-400">No patients yet.</div>
        )}
        {patients.map((p) => (
          <button
            key={p.id}
            onClick={() => open(p)}
            className={
              "w-full text-left p-3 hover:bg-slate-50 " +
              (selected?.id === p.id ? "bg-indigo-50" : "")
            }
          >
            <div className="font-medium">{p.name || "(unnamed)"}</div>
            <div className="text-xs text-slate-400">{p.phone_e164}</div>
            {p.opted_out_at && (
              <span className="text-xs text-red-500">opted out</span>
            )}
          </button>
        ))}
      </div>

      <div className="col-span-2 bg-white border rounded-lg p-4">
        {!selected ? (
          <div className="text-slate-400 text-sm">Select a patient to view their conversation.</div>
        ) : (
          <>
            <div className="mb-3">
              <div className="font-semibold">{selected.name || selected.phone_e164}</div>
              <div className="text-xs text-slate-400">
                {selected.phone_e164} · no-shows: {selected.no_show_count}
              </div>
            </div>
            <div className="space-y-2 max-h-[60vh] overflow-y-auto">
              {messages.length === 0 && (
                <div className="text-sm text-slate-400">No messages.</div>
              )}
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={
                    "max-w-[80%] rounded-lg px-3 py-2 text-sm " +
                    (m.direction === "in"
                      ? "bg-slate-100"
                      : "bg-indigo-600 text-white ml-auto")
                  }
                >
                  {m.body}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
