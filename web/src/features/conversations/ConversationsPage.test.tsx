import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import type { ThreadSummaryResponse } from "../../api/conversations";
import { ConversationsContext, type ConversationsList } from "../../app/conversations";
import { ConversationsPage } from "./ConversationsPage";

const thread = (id: string, title: string | null): ThreadSummaryResponse => ({
  thread_id: id,
  title,
  subjects: [],
  documents: 1,
  last_activity: "2026-09-30T03:00:00Z",
});

const page = (value: Partial<ConversationsList>) => (
  <ConversationsContext.Provider value={{ list: null, failed: false, refresh: () => {}, ...value }}>
    <MemoryRouter initialEntries={["/conversations"]}>
      <Routes>
        <Route path="/conversations" element={<ConversationsPage />} />
        <Route path="/chat" element={<p>New chat page</p>} />
      </Routes>
    </MemoryRouter>
  </ConversationsContext.Provider>
);

describe("ConversationsPage", () => {
  it("lists the conversations with a count", () => {
    render(page({ list: [thread("a", "First"), thread("b", "Second")] }));
    expect(screen.getByRole("heading", { level: 1, name: "Conversations" })).toBeInTheDocument();
    expect(screen.getByText("2 conversations")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "First" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Second" })).toBeInTheDocument();
  });

  it("counts one conversation in the singular", () => {
    render(page({ list: [thread("a", "First")] }));
    expect(screen.getByText("1 conversation")).toBeInTheDocument();
  });

  it("invites the learner to start a conversation when there are none", async () => {
    render(page({ list: [] }));
    expect(screen.getByRole("heading", { name: "No conversations yet" })).toBeInTheDocument();
    expect(screen.getByText("Ask a question about your documents. Every conversation is saved here so you can come back to it.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start a conversation" }));
    expect(screen.getByText("New chat page")).toBeInTheDocument();
  });

  it("says when the list can't load", () => {
    render(page({ list: null, failed: true }));
    expect(screen.getByText("Can't load your conversations. Reload the page to try again.")).toBeInTheDocument();
  });

  it("shows neither table nor empty state while loading", () => {
    render(page({ list: null, failed: false }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("No conversations yet")).not.toBeInTheDocument();
  });

  it("starts a new conversation from the header", async () => {
    render(page({ list: [thread("a", "First")] }));
    await userEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.getByText("New chat page")).toBeInTheDocument();
  });

  it("shows a renamed conversation's new title", () => {
    const { rerender } = render(page({ list: [thread("a", "Old title")] }));
    expect(screen.getByRole("link", { name: "Old title" })).toBeInTheDocument();
    rerender(page({ list: [thread("a", "New title")] }));
    expect(screen.getByRole("link", { name: "New title" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Old title" })).not.toBeInTheDocument();
  });
});
