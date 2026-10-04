import { act, render, screen, within } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { SessionContext } from "../auth/SessionProvider";
import { NAV } from "./nav";
import { routes } from "./routes";

// The Library loads documents from the API; these tests are about routing, so it sees an empty library.
vi.mock("../api/documents", () => ({ loadDocuments: async () => [], uploadPdf: vi.fn() }));

const signOut = vi.fn();

function renderAt(path: string, { strict = false } = {}) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const app = (
    <SessionContext.Provider value={{ name: "Ada Lovelace", signOut }}>
      <RouterProvider router={router} />
    </SessionContext.Provider>
  );
  render(strict ? <StrictMode>{app}</StrictMode> : app);
  return router;
}

const nav = () => within(screen.getByRole("navigation", { name: "Main" }));

describe("app shell routes", () => {
  it("lists the Release 1 nav items in brief order", () => {
    renderAt("/library");
    const labels = nav().getAllByRole("link").map((a) => a.getAttribute("aria-label") ?? a.textContent?.trim());
    expect(labels).toEqual(["Smart Tutor, Library", "Library", "Chat", "Conversations", "Notes", "Subjects", "Usage", "Settings"]);
  });

  it("nav items are links", () => {
    renderAt("/library");
    for (const item of NAV) {
      expect(nav().getByRole("link", { name: item.label })).toHaveAttribute("href", item.path);
    }
  });

  // <Navigate> redirects in an effect, so wait for the Library before reading the location.
  it("redirects / to the Library", async () => {
    const router = renderAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: "Library" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/library");
  });

  it("redirects unknown paths to the Library", async () => {
    const router = renderAt("/nope");
    expect(await screen.findByRole("heading", { level: 1, name: "Library" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/library");
  });

  it("renders the requested page on a deep link", () => {
    renderAt("/notes");
    expect(screen.getByRole("heading", { level: 1, name: "Notes" })).toBeInTheDocument();
    expect(nav().getByRole("link", { name: "Notes" })).toHaveAttribute("aria-current", "page");
    expect(nav().getByRole("link", { name: "Library" })).not.toHaveAttribute("aria-current");
  });

  it("moves to a page and marks it current when a nav item is clicked", async () => {
    renderAt("/library");
    await userEvent.click(nav().getByRole("link", { name: "Usage" }));
    expect(screen.getByRole("heading", { level: 1, name: "Usage" })).toBeInTheDocument();
    expect(nav().getByRole("link", { name: "Usage" })).toHaveAttribute("aria-current", "page");
  });

  it("shows the first-run Library", async () => {
    renderAt("/library");
    expect(await screen.findByRole("heading", { level: 2, name: "Upload your first document" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose PDFs" })).toBeEnabled();
  });

  it("sets the document title from the current page", async () => {
    renderAt("/library");
    expect(document.title).toBe("Library · Smart Tutor");
    await userEvent.click(nav().getByRole("link", { name: "Notes" }));
    expect(document.title).toBe("Notes · Smart Tutor");
  });

  it("shows the learner's name and signs out from the user menu", async () => {
    renderAt("/library");
    await userEvent.click(nav().getByRole("button", { name: /Ada Lovelace/ }));
    await userEvent.click(nav().getByRole("button", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalledOnce();
  });

  it("moves focus to the main region after navigating", async () => {
    renderAt("/library");
    await userEvent.click(nav().getByRole("link", { name: "Usage" }));
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("moves focus to the main region on browser Back", async () => {
    const router = renderAt("/library");
    await userEvent.click(nav().getByRole("link", { name: "Usage" }));
    (document.activeElement as HTMLElement).blur();
    await act(() => router.navigate(-1));
    expect(screen.getByRole("heading", { level: 1, name: "Library" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("leaves focus alone when the app opens at / and redirects", async () => {
    renderAt("/");
    await screen.findByRole("heading", { level: 1, name: "Library" });
    expect(screen.getByRole("main")).not.toHaveFocus();
  });

  it("leaves focus alone on first load in StrictMode", async () => {
    renderAt("/library", { strict: true });
    await screen.findByRole("heading", { level: 1, name: "Library" });
    expect(screen.getByRole("main")).not.toHaveFocus();
  });
});
