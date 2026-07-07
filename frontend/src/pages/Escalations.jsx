import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { LifeBuoy, CheckCheck, Clock, ShieldCheck } from "lucide-react";
import { api } from "../api.js";
import {
  Card,
  Button,
  Badge,
  Avatar,
  EmptyState,
  SkeletonRows,
  toast,
} from "../components/ui/index.js";

export default function Escalations() {
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState(null);

  async function load() {
    try {
      setTickets(await api("/escalations?status=open"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function resolve(id) {
    setResolving(id);
    try {
      await api(`/escalations/${id}/resolve`, { method: "POST" });
      toast.success("Resolved — the bot has resumed this conversation");
      load();
    } catch (e) {
      toast.error(e.message || "Could not resolve");
      setResolving(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Escalations</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Conversations handed to a human. Resolving one resumes the AI receptionist.
          </p>
        </div>
        {!loading && tickets.length > 0 && (
          <Badge tone="warning" dot>
            {tickets.length} open
          </Badge>
        )}
      </div>

      {loading ? (
        <SkeletonRows rows={3} />
      ) : tickets.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title="All caught up"
          description="No open handoffs. The AI receptionist is handling every conversation right now."
        />
      ) : (
        <div className="space-y-2.5">
          {tickets.map((t, i) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i * 0.04, 0.2) }}
            >
              <Card className="flex items-center gap-4 border-l-4 border-l-warning p-4">
                <Avatar name={t.patient_name || t.patient_phone} seed={t.patient_phone} size="md" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold text-foreground">
                    {t.patient_name || t.patient_phone}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <LifeBuoy className="h-3 w-3" />
                      {t.reason || "No reason given"}
                    </span>
                    <span>·</span>
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {new Date(t.created_at).toLocaleString()}
                    </span>
                  </div>
                </div>
                <Button
                  variant="success"
                  size="sm"
                  icon={CheckCheck}
                  loading={resolving === t.id}
                  onClick={() => resolve(t.id)}
                >
                  Resolve
                </Button>
              </Card>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
