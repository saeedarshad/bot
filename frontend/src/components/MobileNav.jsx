import { Fragment } from "react";
import { Dialog, Transition } from "@headlessui/react";
import { X } from "lucide-react";
import { SidebarNav, SidebarLogo } from "./Sidebar.jsx";

export default function MobileNav({ open, onClose, nav, subtitle }) {
  return (
    <Transition show={open} as={Fragment}>
      <Dialog onClose={onClose} className="relative z-50 md:hidden">
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
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="-translate-x-full"
          enterTo="translate-x-0"
          leave="ease-in duration-150"
          leaveFrom="translate-x-0"
          leaveTo="-translate-x-full"
        >
          <Dialog.Panel className="fixed inset-y-0 left-0 flex w-64 flex-col border-r border-border bg-surface">
            <div className="flex h-16 items-center justify-between px-4">
              <SidebarLogo subtitle={subtitle} />
              <button
                onClick={onClose}
                className="rounded-lg p-2 text-muted-foreground hover:bg-surface-hover hover:text-foreground"
                aria-label="Close menu"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <SidebarNav nav={nav} onNavigate={onClose} />
          </Dialog.Panel>
        </Transition.Child>
      </Dialog>
    </Transition>
  );
}
