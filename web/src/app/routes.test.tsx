import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";

import { NAV } from "./nav";
import { routes } from "./routes";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
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

  it("shows the first-run Library", () => {
    renderAt("/library");
    expect(screen.getByRole("heading", { level: 2, name: "Upload your first document" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose PDFs" })).toBeDisabled();
  });

  it("sets the document title from the current page", async () => {
    renderAt("/library");
    expect(document.title).toBe("Library · Smart Tutor");
    await userEvent.click(nav().getByRole("link", { name: "Notes" }));
    expect(document.title).toBe("Notes · Smart Tutor");
  });

  it("moves focus to the main region after navigating", async () => {
    renderAt("/library");
    await userEvent.click(nav().getByRole("link", { name: "Usage" }));
    expect(screen.getByRole("main")).toHaveFocus();
  });
});
