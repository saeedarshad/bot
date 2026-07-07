import { Fragment, useEffect, useMemo, useState } from "react";
import { Dialog, Transition, Combobox } from "@headlessui/react";
import { useNavigate } from "react-router-dom";
import { Search, CornerDownLeft } from "lucide-react";
import { cn } from "../lib/cn.js";

// Lightweight ⌘K command palette: fuzzy-ish filter over the nav items so any
// page is one keystroke away. Small UX addition, no data fetching.
export default function CommandPalette({ open, onClose, nav }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return nav;
    return nav.filter((i) => i.label.toLowerCase().includes(q) || i.section?.toLowerCase().includes(q));
  }, [query, nav]);

  function go(item) {
    if (!item) return;
    onClose();
    navigate(item.to);
  }

  return (
    <Transition show={open} as={Fragment} afterLeave={() => setQuery("")}>
      <Dialog onClose={onClose} className="relative z-50">
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm" />
        </Transition.Child>

        <div className="fixed inset-0 overflow-y-auto p-4 pt-[15vh]">
          <Transition.Child
            as={Fragment}
            enter="ease-out duration-200"
            enterFrom="opacity-0 scale-95"
            enterTo="opacity-100 scale-100"
            leave="ease-in duration-150"
            leaveFrom="opacity-100 scale-100"
            leaveTo="opacity-0 scale-95"
          >
            <Dialog.Panel className="mx-auto max-w-lg overflow-hidden rounded-2xl border border-border bg-surface shadow-lg">
              <Combobox onChange={go}>
                <div className="flex items-center gap-3 border-b border-border px-4">
                  <Search className="h-5 w-5 shrink-0 text-muted-foreground" />
                  <Combobox.Input
                    autoFocus
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Jump to a page…"
                    className="h-12 w-full border-0 bg-transparent text-sm text-foreground placeholder:text-subtle-foreground focus:outline-none focus:ring-0"
                  />
                </div>
                <Combobox.Options static className="max-h-72 overflow-y-auto scrollbar-thin p-2">
                  {results.length === 0 ? (
                    <div className="px-3 py-6 text-center text-sm text-muted-foreground">
                      No matches for “{query}”.
                    </div>
                  ) : (
                    results.map((item) => {
                      const Icon = item.icon;
                      return (
                        <Combobox.Option key={item.to} value={item} as={Fragment}>
                          {({ active }) => (
                            <li
                              className={cn(
                                "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-sm",
                                active
                                  ? "bg-primary/10 text-primary"
                                  : "text-foreground"
                              )}
                            >
                              <Icon className="h-4 w-4 shrink-0" />
                              <span className="flex-1">{item.label}</span>
                              <span className="text-[11px] text-muted-foreground">
                                {item.section}
                              </span>
                              {active && <CornerDownLeft className="h-3.5 w-3.5 text-primary" />}
                            </li>
                          )}
                        </Combobox.Option>
                      );
                    })
                  )}
                </Combobox.Options>
              </Combobox>
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition>
  );
}
