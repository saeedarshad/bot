import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Plus,
  Megaphone,
  Send,
  Eye,
  Power,
  Users,
  DollarSign,
} from "lucide-react";
import { api } from "../api.js";
import { useAuth } from "../lib/auth.jsx";
import {
  Card,
  CardHeader,
  Button,
  Badge,
  Modal,
  Field,
  Input,
  Select,
  Textarea,
  EmptyState,
  SkeletonRows,
  Table,
  THead,
  TH,
  TBody,
  TR,
  TD,
  toast,
  useConfirm,
} from "../components/ui/index.js";
import { fmtMoney, monthDay } from "../lib/format.js";

const BLANK = {
  name: "",
  service: "",
  interval_days: 180,
  window_days: 7,
  template_name: "",
  message_override: "",
  is_active: true,
};

const CAMPAIGN_TONE = { completed: "success", running: "warning" };

export default function Recalls() {
  const { me } = useAuth();
  const currency = me?.clinic?.currency || "USD";
  const confirm = useConfirm();

  const [rules, setRules] = useState([]);
  const [services, setServices] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(BLANK);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState(null); // { ruleId, eligible, projected_cost, sample, loading }
  const [running, setRunning] = useState(false);

  async function load() {
    const [r, s, c] = await Promise.all([
      api("/recall-rules"),
      api("/services"),
      api("/recall-campaigns").catch(() => []),
    ]);
    setRules(r);
    setServices(s);
    setCampaigns(c || []);
    setLoading(false);
  }

  useEffect(() => {
    load().catch((e) => {
      setLoading(false);
      toast.error(e.message);
    });
  }, []);

  async function createRule(e) {
    e.preventDefault();
    setSaving(true);
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
      toast.success("Recall rule created");
      await load();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function doPreview(rule) {
    setPreview({ ruleId: rule.id, loading: true });
    try {
      const p = await api(`/recall-rules/${rule.id}/preview`);
      setPreview({ ruleId: rule.id, ...p });
    } catch (e) {
      setPreview(null);
      toast.error(e.message);
    }
  }

  async function doRun(rule) {
    if (!preview || preview.ruleId !== rule.id) return;
    const ok = await confirm({
      title: "Send this recall campaign?",
      message: `This sends paid marketing messages to ${preview.eligible} patient(s) for an estimated ${fmtMoney(
        currency,
        preview.projected_cost
      )}. This can't be undone.`,
      confirmLabel: `Send to ${preview.eligible}`,
    });
    if (!ok) return;
    setRunning(true);
    try {
      await api(`/recall-rules/${rule.id}/run`, { method: "POST" });
      setPreview(null);
      toast.success("Campaign started");
      await load();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setRunning(false);
    }
  }

  async function toggleActive(rule) {
    try {
      await api(`/recall-rules/${rule.id}`, {
        method: "PATCH",
        body: { is_active: !rule.is_active },
      });
      toast.success(rule.is_active ? "Rule deactivated" : "Rule activated");
      await load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Recall campaigns</h1>
          <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">
            Bring patients back for their next visit. Recalls are paid marketing messages — you
            always preview the count and cost before anything sends.
          </p>
        </div>
        <Button icon={Plus} onClick={() => setShowForm(true)}>
          New rule
        </Button>
      </div>

      {/* Rules */}
      {loading ? (
        <SkeletonRows rows={2} />
      ) : rules.length === 0 ? (
        <EmptyState
          icon={Megaphone}
          title="No recall rules yet"
          description="Create a rule to automatically bring patients back after a set interval — e.g. a 6-month cleaning reminder."
          action={
            <Button icon={Plus} onClick={() => setShowForm(true)}>
              New rule
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {rules.map((rule) => {
            const p = preview && preview.ruleId === rule.id ? preview : null;
            return (
              <Card key={rule.id} className="overflow-hidden">
                <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                      <Megaphone className="h-5 w-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-foreground">
                          {rule.name || `${rule.service_name} recall`}
                        </span>
                        {rule.is_active ? (
                          <Badge tone="success" dot>
                            active
                          </Badge>
                        ) : (
                          <Badge tone="neutral">inactive</Badge>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {rule.service_name} · every {rule.interval_days} days (±{rule.window_days}) ·
                        template <code className="font-mono text-foreground">{rule.template_name}</code>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="ghost" size="sm" icon={Power} onClick={() => toggleActive(rule)}>
                      {rule.is_active ? "Deactivate" : "Activate"}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={Eye}
                      loading={p?.loading}
                      onClick={() => doPreview(rule)}
                    >
                      Preview
                    </Button>
                  </div>
                </div>

                {p && !p.loading && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    className="border-t border-border bg-muted/40 px-4 py-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-4 text-sm">
                        <span className="inline-flex items-center gap-1.5 text-foreground">
                          <Users className="h-4 w-4 text-muted-foreground" />
                          <span className="font-semibold">{p.eligible}</span> eligible
                        </span>
                        <span className="inline-flex items-center gap-1.5 text-foreground">
                          <DollarSign className="h-4 w-4 text-muted-foreground" />
                          projected{" "}
                          <span className="font-semibold">
                            {fmtMoney(currency, p.projected_cost)}
                          </span>
                        </span>
                        {p.sample?.length > 0 && (
                          <span className="hidden text-xs text-muted-foreground md:inline">
                            e.g. {p.sample.join(", ")}
                          </span>
                        )}
                      </div>
                      <Button
                        variant="success"
                        size="sm"
                        icon={Send}
                        loading={running}
                        disabled={p.eligible === 0}
                        onClick={() => doRun(rule)}
                      >
                        Send to {p.eligible}
                      </Button>
                    </div>
                  </motion.div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {/* Campaign history */}
      <Card>
        <CardHeader title="Campaign history" subtitle="Past recall runs and their outcomes" />
        <div className="p-2">
          {campaigns.length === 0 ? (
            <div className="px-2 py-8 text-center text-sm text-muted-foreground">
              No campaigns run yet.
            </div>
          ) : (
            <Table>
              <THead>
                <TH>Date</TH>
                <TH>Rule</TH>
                <TH>Status</TH>
                <TH className="text-right">Eligible</TH>
                <TH className="text-right">Sent</TH>
                <TH className="text-right">Skipped</TH>
                <TH className="text-right">Cost</TH>
              </THead>
              <TBody>
                {campaigns.map((c) => (
                  <TR key={c.id}>
                    <TD className="whitespace-nowrap">{monthDay(c.created_at)}</TD>
                    <TD>{c.service_name}</TD>
                    <TD>
                      <Badge tone={CAMPAIGN_TONE[c.status] || "neutral"}>{c.status}</Badge>
                    </TD>
                    <TD className="text-right tabular-nums">{c.eligible}</TD>
                    <TD className="text-right tabular-nums">{c.sent}</TD>
                    <TD className="text-right tabular-nums">{c.skipped}</TD>
                    <TD className="text-right tabular-nums">{fmtMoney(currency, c.actual_cost)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </div>
      </Card>

      {/* New rule modal */}
      <Modal
        open={showForm}
        onClose={() => setShowForm(false)}
        title="New recall rule"
        description="Define who gets recalled and when."
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowForm(false)}>
              Cancel
            </Button>
            <Button form="recall-form" type="submit" loading={saving}>
              Save rule
            </Button>
          </>
        }
      >
        <form id="recall-form" onSubmit={createRule} className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" className="sm:col-span-2">
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="6-month cleaning recall"
            />
          </Field>
          <Field label="Service" required>
            <Select
              required
              value={form.service}
              onChange={(e) => setForm({ ...form, service: e.target.value })}
            >
              <option value="">Select a service…</option>
              {services.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Meta template name" required>
            <Input
              required
              value={form.template_name}
              onChange={(e) => setForm({ ...form, template_name: e.target.value })}
              placeholder="recall_checkup"
            />
          </Field>
          <Field label="Recall after (days)" required>
            <Input
              type="number"
              min="1"
              required
              value={form.interval_days}
              onChange={(e) => setForm({ ...form, interval_days: e.target.value })}
            />
          </Field>
          <Field label="Window (± days)">
            <Input
              type="number"
              min="0"
              value={form.window_days}
              onChange={(e) => setForm({ ...form, window_days: e.target.value })}
            />
          </Field>
          <Field
            label="Message override"
            hint="Fallback text when no template maps. {name} and {clinic} are substituted."
            className="sm:col-span-2"
          >
            <Textarea
              rows={2}
              value={form.message_override}
              onChange={(e) => setForm({ ...form, message_override: e.target.value })}
              placeholder="Hi {name}, it's time for your checkup at {clinic}!"
            />
          </Field>
        </form>
      </Modal>
    </div>
  );
}
