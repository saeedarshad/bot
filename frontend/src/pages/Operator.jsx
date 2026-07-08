import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Building2,
  Plus,
  Users,
  CircleCheck,
  CircleSlash,
  Trash2,
  Settings2,
  UserPlus,
  Save,
} from "lucide-react";
import { api } from "../api.js";
import { TIMEZONES, CURRENCIES } from "../lib/options.js";
import {
  Card,
  StatCard,
  Button,
  Badge,
  Modal,
  Field,
  Input,
  Select,
  Textarea,
  EmptyState,
  SkeletonRows,
  Avatar,
  Table,
  THead,
  TH,
  TBody,
  TR,
  TD,
  toast,
  useConfirm,
} from "../components/ui/index.js";

const BLANK_CLINIC = {
  name: "",
  timezone: "America/New_York",
  currency: "USD",
  whatsapp_phone_number_id: "",
  plan: "demo",
  staff_username: "",
  staff_password: "",
};

const SUB_TONE = { active: "success", suspended: "danger", cancelled: "neutral" };

export default function Operator() {
  const [clinics, setClinics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [manage, setManage] = useState(null);

  async function load() {
    try {
      setClinics(await api("/admin/clinics"));
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const stats = useMemo(() => {
    const active = clinics.filter((c) => c.subscription?.status === "active").length;
    const suspended = clinics.filter((c) => c.subscription?.status === "suspended").length;
    const patients = clinics.reduce((s, c) => s + (c.patient_count || 0), 0);
    return { total: clinics.length, active, suspended, patients };
  }, [clinics]);

  // Keep the manage modal's clinic in sync with fresh list data.
  const manageClinic = manage ? clinics.find((c) => c.id === manage) : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Clinics</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Add or remove clinics and set each one's pay status. Suspending a clinic cuts off its
            dashboard and its bot.
          </p>
        </div>
        <Button icon={Plus} onClick={() => setShowCreate(true)}>
          New clinic
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard index={0} label="Clinics" value={stats.total} icon={Building2} accent="primary" />
        <StatCard index={1} label="Active" value={stats.active} icon={CircleCheck} accent="success" />
        <StatCard
          index={2}
          label="Suspended"
          value={stats.suspended}
          icon={CircleSlash}
          accent="danger"
        />
        <StatCard index={3} label="Total patients" value={stats.patients} icon={Users} accent="info" />
      </div>

      <Card>
        {loading ? (
          <div className="p-4">
            <SkeletonRows rows={4} />
          </div>
        ) : clinics.length === 0 ? (
          <EmptyState
            icon={Building2}
            title="No clinics yet"
            description="Create your first clinic to get started."
            action={
              <Button icon={Plus} onClick={() => setShowCreate(true)}>
                New clinic
              </Button>
            }
            className="border-0"
          />
        ) : (
          <div className="p-2">
            <Table>
              <THead>
                <TH>Clinic</TH>
                <TH>Timezone</TH>
                <TH>Plan</TH>
                <TH>Status</TH>
                <TH>Paid through</TH>
                <TH className="text-right">Staff</TH>
                <TH className="text-right">Patients</TH>
                <TH className="text-right"></TH>
              </THead>
              <TBody>
                {clinics.map((c) => {
                  const sub = c.subscription || {};
                  return (
                    <TR key={c.id}>
                      <TD>
                        <div className="flex items-center gap-3">
                          <Avatar name={c.name} seed={c.slug} size="sm" />
                          <div>
                            <div className="font-medium text-foreground">{c.name}</div>
                            <div className="text-xs text-muted-foreground">{c.slug}</div>
                          </div>
                        </div>
                      </TD>
                      <TD className="text-muted-foreground">{c.timezone}</TD>
                      <TD>{sub.plan || "—"}</TD>
                      <TD>
                        <Badge tone={SUB_TONE[sub.status] || "neutral"} dot>
                          {sub.status || "—"}
                        </Badge>
                      </TD>
                      <TD className="text-muted-foreground">{sub.paid_through || "—"}</TD>
                      <TD className="text-right tabular-nums text-muted-foreground">
                        {c.staff_count}
                      </TD>
                      <TD className="text-right tabular-nums text-muted-foreground">
                        {c.patient_count}
                      </TD>
                      <TD className="text-right">
                        <Button
                          variant="secondary"
                          size="sm"
                          icon={Settings2}
                          onClick={() => setManage(c.id)}
                        >
                          Manage
                        </Button>
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          </div>
        )}
      </Card>

      <CreateClinicModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => {
          setShowCreate(false);
          toast.success("Clinic created");
          load();
        }}
      />

      <ManageClinicModal
        clinic={manageClinic}
        onClose={() => setManage(null)}
        onChanged={load}
        onDeleted={() => {
          setManage(null);
          load();
        }}
      />
    </div>
  );
}

function CreateClinicModal({ open, onClose, onCreated }) {
  const [form, setForm] = useState(BLANK_CLINIC);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/admin/clinics", { method: "POST", body: form });
      setForm(BLANK_CLINIC);
      onCreated();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New clinic"
      description="Creates a clinic with an active subscription and an optional first staff login."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button form="create-clinic" type="submit" loading={busy}>
            Create clinic
          </Button>
        </>
      }
    >
      <form id="create-clinic" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Clinic name" required className="sm:col-span-2">
          <Input required value={form.name} onChange={set("name")} placeholder="Bright Smiles Dental" />
        </Field>
        <Field label="Timezone">
          <Select value={form.timezone} onChange={set("timezone")}>
            {TIMEZONES.map(([value, name]) => (
              <option key={value} value={value}>
                {name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Currency">
          <Select value={form.currency} onChange={set("currency")}>
            {CURRENCIES.map(([value, name]) => (
              <option key={value} value={value}>
                {name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="WhatsApp phone_number_id" hint="Optional" className="sm:col-span-2">
          <Input value={form.whatsapp_phone_number_id} onChange={set("whatsapp_phone_number_id")} />
        </Field>
        <Field label="Plan">
          <Input value={form.plan} onChange={set("plan")} />
        </Field>
        <div className="sm:col-span-2 border-t border-border pt-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          First staff login (optional)
        </div>
        <Field label="Staff username">
          <Input value={form.staff_username} onChange={set("staff_username")} autoComplete="off" />
        </Field>
        <Field label="Staff password" hint="8+ characters">
          <Input
            type="password"
            value={form.staff_password}
            onChange={set("staff_password")}
            autoComplete="new-password"
          />
        </Field>
      </form>
    </Modal>
  );
}

function ManageClinicModal({ clinic, onClose, onChanged, onDeleted }) {
  const confirm = useConfirm();
  const [form, setForm] = useState(null);
  const [staff, setStaff] = useState(null);
  const [newStaff, setNewStaff] = useState({ username: "", password: "" });
  const [savingSub, setSavingSub] = useState(false);
  const [addingStaff, setAddingStaff] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!clinic) {
      setForm(null);
      setStaff(null);
      setNewStaff({ username: "", password: "" });
      return;
    }
    const sub = clinic.subscription || {};
    setForm({
      plan: sub.plan || "demo",
      status: sub.status || "active",
      paid_through: sub.paid_through || "",
      notes: sub.notes || "",
    });
    api(`/admin/clinics/${clinic.id}/staff`)
      .then(setStaff)
      .catch((e) => toast.error(e.message));
  }, [clinic]);

  async function saveSubscription(e) {
    e.preventDefault();
    setSavingSub(true);
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
      toast.success("Subscription updated");
      await onChanged();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSavingSub(false);
    }
  }

  async function addStaff(e) {
    e.preventDefault();
    setAddingStaff(true);
    try {
      const list = await api(`/admin/clinics/${clinic.id}/staff`, {
        method: "POST",
        body: newStaff,
      });
      setStaff(list);
      setNewStaff({ username: "", password: "" });
      toast.success("Staff added");
      await onChanged();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setAddingStaff(false);
    }
  }

  async function remove() {
    const ok = await confirm({
      title: `Delete ${clinic.name}?`,
      message:
        "This permanently removes the clinic and ALL its patients, appointments, and messages. This cannot be undone.",
      confirmLabel: "Delete clinic",
      danger: true,
    });
    if (!ok) return;
    setDeleting(true);
    try {
      await api(`/admin/clinics/${clinic.id}`, { method: "DELETE" });
      toast.success("Clinic deleted");
      onDeleted();
    } catch (e) {
      toast.error(e.message);
      setDeleting(false);
    }
  }

  return (
    <Modal
      open={!!clinic}
      onClose={onClose}
      title={clinic ? `Manage ${clinic.name}` : "Manage"}
      description={clinic?.slug}
      size="lg"
    >
      {clinic && form && (
        <div className="space-y-6">
          {/* Subscription */}
          <form onSubmit={saveSubscription} className="space-y-4">
            <div className="text-sm font-semibold text-foreground">Subscription</div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Status">
                <Select
                  value={form.status}
                  onChange={(e) => setForm({ ...form, status: e.target.value })}
                >
                  <option value="active">active</option>
                  <option value="suspended">suspended</option>
                  <option value="cancelled">cancelled</option>
                </Select>
              </Field>
              <Field label="Plan">
                <Input value={form.plan} onChange={(e) => setForm({ ...form, plan: e.target.value })} />
              </Field>
              <Field label="Paid through">
                <Input
                  type="date"
                  value={form.paid_through || ""}
                  onChange={(e) => setForm({ ...form, paid_through: e.target.value })}
                />
              </Field>
            </div>
            <Field label="Notes">
              <Textarea
                rows={2}
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
              />
            </Field>
            <Button type="submit" size="sm" icon={Save} loading={savingSub}>
              Save subscription
            </Button>
          </form>

          {/* Staff */}
          <div className="space-y-3 border-t border-border pt-5">
            <div className="text-sm font-semibold text-foreground">Staff logins</div>
            <ul className="space-y-1.5">
              {staff === null ? (
                <li className="text-sm text-muted-foreground">Loading…</li>
              ) : staff.length === 0 ? (
                <li className="text-sm text-muted-foreground">No staff logins yet.</li>
              ) : (
                staff.map((s) => (
                  <li key={s.id} className="flex items-center gap-2.5 text-sm">
                    <Avatar name={s.username} size="sm" />
                    <span className="font-medium text-foreground">{s.username}</span>
                    {!s.is_active && <Badge tone="neutral">disabled</Badge>}
                  </li>
                ))
              )}
            </ul>
            <form onSubmit={addStaff} className="flex flex-wrap items-end gap-2">
              <Field label="Username" className="min-w-[140px] flex-1">
                <Input
                  value={newStaff.username}
                  onChange={(e) => setNewStaff({ ...newStaff, username: e.target.value })}
                  autoComplete="off"
                />
              </Field>
              <Field label="Password" className="min-w-[140px] flex-1">
                <Input
                  type="password"
                  value={newStaff.password}
                  onChange={(e) => setNewStaff({ ...newStaff, password: e.target.value })}
                  autoComplete="new-password"
                />
              </Field>
              <Button type="submit" variant="secondary" icon={UserPlus} loading={addingStaff}>
                Add
              </Button>
            </form>
          </div>

          {/* Danger zone */}
          <div className="flex items-center justify-between rounded-xl border border-danger/25 bg-danger/5 px-4 py-3">
            <div>
              <div className="text-sm font-medium text-foreground">Delete this clinic</div>
              <div className="text-xs text-muted-foreground">
                Removes all patients, appointments, and messages.
              </div>
            </div>
            <Button variant="danger" size="sm" icon={Trash2} loading={deleting} onClick={remove}>
              Delete
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
