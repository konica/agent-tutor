import { createContext, useContext, useEffect } from "react";

/** Set by AppShell: whether a page currently forces the app nav to its rail. */
export const NavRailContext = createContext<(on: boolean) => void>(() => {});

/** While `on`, the app nav shows its rail; the learner's own choice comes back when it turns off or the caller unmounts. */
export function useForceNavRail(on: boolean): void {
  const setForced = useContext(NavRailContext);
  useEffect(() => {
    setForced(on);
    return () => setForced(false);
  }, [on, setForced]);
}
