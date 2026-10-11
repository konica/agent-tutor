import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ThreadSummaryResponse } from "../../api/conversations";
import { SessionContext } from "../../auth/SessionProvider";
import { AppShell } from "./AppShell";

const thread = (id: string, title: string): ThreadSummaryResponse => ({
  thread_id: id,
  title,
  subjects: [],
  documents: 1,
  last_activity: "2026-10-11T02:48:00Z",
});

function renderShell(conversations: ThreadSummaryResponse[]) {
  const shell = <AppShell loadDocuments={async () => []} loadConversations={async () => conversations} />;
  const router = createMemoryRouter([{ element: shell, children: [{ path: "library", element: <p>Library page</p> }] }], {
    initialEntries: ["/library"],
  });
  render(
    <SessionContext.Provider value={{ name: "Ada Lovelace", signOut: vi.fn() }}>
      <RouterProvider router={router} />
    </SessionContext.Provider>,
  );
}

describe("AppShell recent conversations", () => {
  it("lists the learner's recent conversations in the side nav as links to them", async () => {
    renderShell([thread("t1", "What is attention?"), thread("t2", "Gradient descent")]);
    const list = await screen.findByRole("list", { name: "Recent conversations" });
    const links = within(list).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["What is attention?", "Gradient descent"]);
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/chat/t1", "/chat/t2"]);
  });

  it("shows no list when there are none", async () => {
    renderShell([]);
    await screen.findByText("Library page");
    expect(screen.queryByRole("list", { name: "Recent conversations" })).not.toBeInTheDocument();
  });
});
