import { useCallback, useState } from "react";

const KEY = "smart-tutor.nav-collapsed";

// The nav's rail choice survives a reload (DESIGN.md → Layout); blocked storage just forgets it.
export function useNavCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggle = useCallback(() => {
    setCollapsed((was) => {
      try {
        localStorage.setItem(KEY, was ? "0" : "1");
      } catch {
        // keep the choice for this visit only
      }
      return !was;
    });
  }, []);
  return [collapsed, toggle];
}
