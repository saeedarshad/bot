import { createContext, useCallback, useContext, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import Modal from "./Modal.jsx";
import Button from "./Button.jsx";

const ConfirmContext = createContext(() => Promise.resolve(false));

// Promise-based confirm. Usage:
//   const confirm = useConfirm();
//   if (await confirm({ title, message, danger: true })) { ... }
export function ConfirmProvider({ children }) {
  const [state, setState] = useState(null);
  const resolver = useRef(null);

  const confirm = useCallback((opts) => {
    setState({
      title: "Are you sure?",
      confirmLabel: "Confirm",
      cancelLabel: "Cancel",
      danger: false,
      ...opts,
    });
    return new Promise((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const close = (result) => {
    resolver.current?.(result);
    resolver.current = null;
    setState(null);
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Modal
        open={!!state}
        onClose={() => close(false)}
        title={state?.title}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => close(false)}>
              {state?.cancelLabel}
            </Button>
            <Button
              variant={state?.danger ? "danger" : "primary"}
              onClick={() => close(true)}
              autoFocus
            >
              {state?.confirmLabel}
            </Button>
          </>
        }
      >
        <div className="flex gap-3">
          {state?.danger && (
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-danger/10">
              <AlertTriangle className="h-5 w-5 text-danger" />
            </div>
          )}
          <p className="text-sm text-muted-foreground">{state?.message}</p>
        </div>
      </Modal>
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  return useContext(ConfirmContext);
}
