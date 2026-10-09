import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionContext } from "../../auth/SessionProvider";
import { AppShell } from "./AppShell";
import { useForceNavRail } from "./NavRail";

function Forcing() {
  useForceNavRail(true);
  return <p>Split view</p>;
}

// A page that forces the rail while its "split" is open, and can close it.
function Page() {
  const [split, setSplit] = useState(true);
  return (
    <>
      {split && <Forcing />}
      <button type="button" onClick={() => setSplit(false)}>
        Close split
      </button>
    </>
  );
}

function renderShell() {
  const router = createMemoryRouter([{ element: <AppShell />, children: [{ path: "chat", element: <Page /> }] }], {
    initialEntries: ["/chat"],
  });
  render(
    <SessionContext.Provider value={{ name: "Ada Lovelace", signOut: vi.fn() }}>
      <RouterProvider router={router} />
    </SessionContext.Provider>,
  );
}

const navToggle = (name: RegExp) => screen.getByRole("button", { name });

afterEach(() => localStorage.clear());

describe("useForceNavRail", () => {
  it("drops the nav to its rail while on, and restores it when the caller unmounts", async () => {
    renderShell();
    await screen.findByText("Split view");
    expect(navToggle(/navigation/)).toHaveAttribute("aria-expanded", "false");
    expect(navToggle(/navigation/)).toHaveAccessibleName("Expand navigation");
    await userEvent.click(screen.getByRole("button", { name: "Close split" }));
    expect(navToggle(/navigation/)).toHaveAttribute("aria-expanded", "true");
  });

  it("lets the learner re-open the nav without changing the saved choice", async () => {
    renderShell();
    await screen.findByText("Split view");
    await userEvent.click(navToggle(/Expand navigation/));
    expect(navToggle(/navigation/)).toHaveAttribute("aria-expanded", "true");
    expect(localStorage.getItem("smart-tutor.nav-collapsed")).toBeNull();
  });
});
