import { useCallback, useState } from "react";

const KEY = "smart-tutor.chat-panel-open";

// Storage can be missing or blocked (private windows, blocked site data): the panel then starts open and the choice lasts for the page.
function read(): boolean {
  try {
    return localStorage.getItem(KEY) !== "false";
  } catch {
    return true;
  }
}

function write(open: boolean) {
  try {
    localStorage.setItem(KEY, String(open));
  } catch {
    // Not remembered; the page still works.
  }
}

/** Whether the chat's conversation panel is open; the learner's choice is remembered (DESIGN.md → Chat). */
export function usePanelOpen(): [open: boolean, toggle: () => void] {
  const [open, setOpen] = useState(read);
  const toggle = useCallback(() => {
    setOpen((was) => {
      write(!was);
      return !was;
    });
  }, []);
  return [open, toggle];
}
