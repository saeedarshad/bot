import { useState } from "react";
import { motion } from "framer-motion";
import {
  Sparkles,
  CalendarCheck,
  MessageSquareHeart,
  TrendingUp,
  ArrowRight,
} from "lucide-react";
import { api } from "../api.js";
import { Button, Field, Input } from "../components/ui/index.js";
import ThemeToggle from "../components/ui/ThemeToggle.jsx";

const HIGHLIGHTS = [
  {
    icon: MessageSquareHeart,
    title: "Answers patients 24/7",
    body: "WhatsApp replies in seconds, day or night.",
  },
  {
    icon: CalendarCheck,
    title: "Books into your calendar",
    body: "Deterministic scheduling — never a double-booking.",
  },
  {
    icon: TrendingUp,
    title: "Recovers lost revenue",
    body: "Recalls, waitlists, and no-show rebooking on autopilot.",
  },
];

export default function Login({ onLoggedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/login", { method: "POST", body: { username, password } });
      onLoggedIn();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full">
      {/* Brand panel */}
      <div className="relative hidden w-1/2 overflow-hidden bg-gradient-to-br from-primary via-indigo-600 to-accent lg:flex">
        <div className="absolute inset-0 bg-grid opacity-20" />
        <div className="absolute -left-24 -top-24 h-96 w-96 rounded-full bg-white/10 blur-3xl" />
        <div className="absolute -bottom-32 right-0 h-96 w-96 rounded-full bg-accent/30 blur-3xl" />
        <div className="relative z-10 flex flex-col justify-between p-12 text-white">
          <div className="flex items-center gap-2.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/15 ring-1 ring-white/25 backdrop-blur">
              <Sparkles className="h-5 w-5" />
            </div>
            <span className="text-lg font-bold">Receptionaly</span>
          </div>

          <div className="max-w-md">
            <motion.h1
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="text-3xl font-bold leading-tight"
            >
              The AI receptionist that never misses a patient.
            </motion.h1>
            <div className="mt-8 space-y-4">
              {HIGHLIGHTS.map((h, i) => (
                <motion.div
                  key={h.title}
                  initial={{ opacity: 0, x: -12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.4, delay: 0.15 + i * 0.1 }}
                  className="flex items-start gap-3.5"
                >
                  <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/15 ring-1 ring-white/20">
                    <h.icon className="h-4.5 w-4.5" />
                  </div>
                  <div>
                    <div className="font-semibold">{h.title}</div>
                    <div className="text-sm text-white/75">{h.body}</div>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>

          <div className="text-sm text-white/60">
            © {new Date().getFullYear()} Receptionaly AI · HIPAA-minded messaging
          </div>
        </div>
      </div>

      {/* Form panel */}
      <div className="relative flex w-full items-center justify-center px-4 py-12 lg:w-1/2">
        <div className="absolute right-4 top-4">
          <ThemeToggle />
        </div>
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="w-full max-w-sm"
        >
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-2.5">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent">
                <Sparkles className="h-5 w-5 text-white" />
              </div>
              <span className="text-lg font-bold text-foreground">Receptionaly</span>
            </div>
          </div>

          <h2 className="text-2xl font-bold text-foreground">Welcome back</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Sign in to your clinic dashboard.
          </p>

          <form onSubmit={submit} className="mt-8 space-y-4">
            {error && (
              <div className="animate-fade-in rounded-lg border border-danger/30 bg-danger/10 px-3.5 py-2.5 text-sm text-danger">
                {error}
              </div>
            )}
            <Field label="Username" htmlFor="username">
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                placeholder="demo"
              />
            </Field>
            <Field label="Password" htmlFor="password">
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="••••••••"
              />
            </Field>
            <Button
              type="submit"
              size="lg"
              loading={busy}
              className="w-full"
              iconRight={busy ? undefined : ArrowRight}
            >
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            Trouble signing in? Contact your Receptionaly operator.
          </p>
        </motion.div>
      </div>
    </div>
  );
}
