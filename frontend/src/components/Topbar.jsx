import { Fragment } from "react";
import { Menu, Transition } from "@headlessui/react";
import { useLocation } from "react-router-dom";
import { Menu as MenuIcon, Search, LogOut, ChevronDown } from "lucide-react";
import ThemeToggle from "./ui/ThemeToggle.jsx";
import Avatar from "./ui/Avatar.jsx";
import Badge from "./ui/Badge.jsx";
import { cn } from "../lib/cn.js";

function useTitle(nav) {
  const { pathname } = useLocation();
  const match =
    nav.find((i) => (i.end ? pathname === i.to : pathname.startsWith(i.to) && i.to !== "/")) ||
    nav.find((i) => i.to === "/" && pathname === "/");
  return match?.label || "Dashboard";
}

export default function Topbar({ nav, me, onLogout, onOpenMobile, onOpenSearch, badge }) {
  const title = useTitle(nav);
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur-md sm:px-6">
      <button
        onClick={onOpenMobile}
        className="rounded-lg p-2 text-muted-foreground hover:bg-surface-hover hover:text-foreground md:hidden"
        aria-label="Open menu"
      >
        <MenuIcon className="h-5 w-5" />
      </button>

      <div className="min-w-0 flex items-center gap-2.5">
        <h1 className="truncate text-lg font-semibold text-foreground">{title}</h1>
        {badge}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={onOpenSearch}
          className="hidden items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-surface-hover sm:flex"
        >
          <Search className="h-4 w-4" />
          <span>Search…</span>
          <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
            ⌘K
          </kbd>
        </button>
        <button
          onClick={onOpenSearch}
          className="rounded-lg p-2 text-muted-foreground hover:bg-surface-hover hover:text-foreground sm:hidden"
          aria-label="Search"
        >
          <Search className="h-5 w-5" />
        </button>

        <ThemeToggle />

        <Menu as="div" className="relative">
          <Menu.Button className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 transition-colors hover:bg-surface-hover">
            <Avatar name={me?.username} size="sm" />
            <span className="hidden text-sm font-medium text-foreground sm:block">
              {me?.username}
            </span>
            <ChevronDown className="hidden h-4 w-4 text-muted-foreground sm:block" />
          </Menu.Button>
          <Transition
            as={Fragment}
            enter="transition ease-out duration-150"
            enterFrom="opacity-0 scale-95 -translate-y-1"
            enterTo="opacity-100 scale-100 translate-y-0"
            leave="transition ease-in duration-100"
            leaveFrom="opacity-100"
            leaveTo="opacity-0 scale-95"
          >
            <Menu.Items className="absolute right-0 mt-2 w-60 origin-top-right rounded-xl border border-border bg-surface p-1.5 shadow-lg focus:outline-none">
              <div className="flex items-center gap-3 rounded-lg px-2.5 py-2">
                <Avatar name={me?.username} size="md" />
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-foreground">
                    {me?.username}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {me?.is_superuser ? "Platform operator" : me?.clinic?.name}
                  </div>
                </div>
              </div>
              {me?.is_superuser && (
                <div className="px-2.5 pb-1.5">
                  <Badge tone="accent" dot>
                    Operator
                  </Badge>
                </div>
              )}
              <div className="my-1 h-px bg-border" />
              <Menu.Item>
                {({ active }) => (
                  <button
                    onClick={onLogout}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-danger transition-colors",
                      active && "bg-danger/10"
                    )}
                  >
                    <LogOut className="h-4 w-4" />
                    Sign out
                  </button>
                )}
              </Menu.Item>
            </Menu.Items>
          </Transition>
        </Menu>
      </div>
    </header>
  );
}
