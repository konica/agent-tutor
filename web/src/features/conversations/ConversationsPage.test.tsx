import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ConversationFilters, ThreadSummaryResponse } from "../../api/conversations";
import type { SubjectResponse } from "../../api/generated/types.gen";
import { ConversationsContext, type ConversationsList } from "../../app/conversations";
import { ConversationsPage } from "./ConversationsPage";

const thread = (id: string, title: string | null): ThreadSummaryResponse => ({
  thread_id: id,
  title,
  subjects: [],
  documents: 1,
  last_activity: "2026-09-30T03:00:00Z",
});

const subjects = [{ subject_id: "s1", name: "Biology" }] as SubjectResponse[];
const noFilteredRows = async (_: ConversationFilters): Promise<ThreadSummaryResponse[]> => [];

const page = (
  value: Partial<ConversationsList>,
  loadConversations: (f: ConversationFilters) => Promise<ThreadSummaryResponse[]> = noFilteredRows,
) => (
  <ConversationsContext.Provider value={{ list: null, failed: false, refresh: () => {}, ...value }}>
    <MemoryRouter initialEntries={["/conversations"]}>
      <Routes>
        <Route path="/conversations" element={<ConversationsPage loadConversations={loadConversations} loadSubjects={async () => subjects} />} />
        <Route path="/chat" element={<p>New chat page</p>} />
      </Routes>
    </MemoryRouter>
  </ConversationsContext.Provider>
);

describe("ConversationsPage", () => {
  it("lists the conversations with a count", () => {
    render(page({ list: [thread("a", "First"), thread("b", "Second")] }));
    expect(screen.getByRole("heading", { level: 1, name: "Conversations" })).toBeInTheDocument();
    expect(screen.getAllByText("2 conversations")).toHaveLength(2); // header and filter bar
    expect(screen.getByRole("link", { name: "First" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Second" })).toBeInTheDocument();
  });

  it("counts one conversation in the singular", () => {
    render(page({ list: [thread("a", "First")] }));
    expect(screen.getAllByText("1 conversation")).toHaveLength(2); // header and filter bar
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

  it("narrows the list by subject, counting the bar and keeping the header total", async () => {
    const load = vi.fn(async () => [thread("a", "First")]);
    render(page({ list: [thread("a", "First"), thread("b", "Second")] }, load));
    await screen.findByRole("option", { name: "Biology" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Subject" }), "Biology");
    expect(await screen.findByText("1 conversation")).toBeInTheDocument(); // the bar; the header still says 2
    expect(load).toHaveBeenLastCalledWith({ subject_id: "s1" });
    expect(screen.queryByRole("link", { name: "Second" })).not.toBeInTheDocument();
    expect(screen.getByText("2 conversations")).toBeInTheDocument();
  });

  it("explains an empty result and clears the filters", async () => {
    render(page({ list: [thread("a", "First"), thread("b", "Second")] }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search titles" }), "zzz");
    expect(await screen.findByRole("heading", { name: "No conversations match these filters" })).toBeInTheDocument();
    expect(screen.getByText("Try another subject, a wider date range or another search.")).toBeInTheDocument();
    const clear = screen.getAllByRole("button", { name: "Clear filters" });
    await userEvent.click(clear[clear.length - 1]!);
    expect(screen.getByRole("link", { name: "First" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Second" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search titles" })).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });

  it("does not treat a blank search as a filter", async () => {
    const load = vi.fn(async () => []);
    render(page({ list: [thread("a", "First")] }, load));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search titles" }), "  ");
    expect(screen.getByRole("link", { name: "First" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
    expect(load).not.toHaveBeenCalled();
  });

  it("shows no filter bar when there are no conversations", () => {
    render(page({ list: [] }));
    expect(screen.getByRole("heading", { name: "No conversations yet" })).toBeInTheDocument();
    expect(screen.queryByRole("search")).not.toBeInTheDocument();
  });
});
