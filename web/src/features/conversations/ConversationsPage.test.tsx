import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ThreadSummaryResponse } from "../../api/conversations";
import { SessionExpiredError } from "../../auth/authClient";
import { ConversationsContext, type ConversationsList } from "../../app/conversations";
import { ConversationsPage } from "./ConversationsPage";

const thread = (id: string, title: string | null): ThreadSummaryResponse => ({
  thread_id: id,
  title,
  subjects: [],
  documents: 1,
  last_activity: "2026-09-30T03:00:00Z",
});

type Injected = ComponentProps<typeof ConversationsPage>;

const page = (value: Partial<ConversationsList>, props: Injected = {}) => (
  <ConversationsContext.Provider value={{ list: null, failed: false, refresh: () => {}, ...value }}>
    <MemoryRouter initialEntries={["/conversations"]}>
      <Routes>
        <Route path="/conversations" element={<ConversationsPage loadArchived={async () => []} {...props} />} />
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
    expect(await screen.findByRole("heading", { name: "No conversations yet" })).toBeInTheDocument();
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

  describe("archiving", () => {
    const chooseAction = async (title: string, action: string) => {
      await userEvent.click(await screen.findByRole("button", { name: `Actions for ${title}` }));
      await userEvent.click(screen.getByRole("menuitem", { name: action }));
    };

    it("tabs show active and archived counts", async () => {
      render(page({ list: [thread("a", "First"), thread("b", "Second")] }, { loadArchived: vi.fn().mockResolvedValue([thread("c", "Old")]) }));
      expect(await screen.findByRole("tab", { name: /^Archived\s*1$/ })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /^Active\s*2$/ })).toHaveAttribute("aria-selected", "true");
      expect(screen.getByText("2 conversations")).toBeInTheDocument();
    });

    it("the Archived tab lists archived conversations with the notice", async () => {
      render(page({ list: [thread("a", "First")] }, { loadArchived: vi.fn().mockResolvedValue([thread("c", "Old")]) }));
      await userEvent.click(await screen.findByRole("tab", { name: /^Archived\s*1$/ }));
      expect(screen.getByRole("link", { name: "Old" })).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "First" })).not.toBeInTheDocument();
      expect(screen.getByText("Archived conversations stay readable. Restore one to keep asking.")).toBeInTheDocument();
    });

    it("an empty Archived tab", async () => {
      render(page({ list: [thread("a", "First")] }));
      await userEvent.click(await screen.findByRole("tab", { name: /^Archived\s*0$/ }));
      expect(screen.getByRole("heading", { name: "No archived conversations" })).toBeInTheDocument();
      expect(screen.getByText("Conversations you archive appear here. You can restore them at any time.")).toBeInTheDocument();
    });

    it("Active empty while archived exist", async () => {
      render(page({ list: [] }, { loadArchived: vi.fn().mockResolvedValue([thread("c", "Old")]) }));
      expect(await screen.findByRole("heading", { name: "No active conversations" })).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Start a conversation" }));
      expect(screen.getByText("New chat page")).toBeInTheDocument();
    });

    it("archiving from the list refreshes the shell list", async () => {
      const archive = vi.fn().mockResolvedValue({});
      const refresh = vi.fn();
      const loadArchived = vi.fn().mockResolvedValue([]);
      render(page({ list: [thread("a", "First")], refresh }, { archive, loadArchived }));
      await waitFor(() => expect(loadArchived).toHaveBeenCalledTimes(1));
      await chooseAction("First", "Archive");
      expect(archive).toHaveBeenCalledWith("a");
      await waitFor(() => expect(loadArchived).toHaveBeenCalledTimes(2));
      expect(refresh).toHaveBeenCalled();
      expect(await screen.findByText("First archived. Find it under Archived.")).toBeInTheDocument();
    });

    it("restoring from the Archived tab", async () => {
      const restore = vi.fn().mockResolvedValue({});
      const refresh = vi.fn();
      const loadArchived = vi.fn().mockResolvedValue([thread("c", "Old")]);
      render(page({ list: [], refresh }, { restore, loadArchived }));
      await userEvent.click(await screen.findByRole("tab", { name: /^Archived\s*1$/ }));
      await chooseAction("Old", "Restore");
      expect(restore).toHaveBeenCalledWith("c");
      await waitFor(() => expect(loadArchived).toHaveBeenCalledTimes(2));
      expect(refresh).toHaveBeenCalled();
      expect(await screen.findByText("Old restored.")).toBeInTheDocument();
    });

    it("a failed archive says so", async () => {
      const archive = vi.fn().mockRejectedValue(new Error("x"));
      render(page({ list: [thread("a", "First")] }, { archive }));
      await chooseAction("First", "Archive");
      expect(await screen.findByText("Couldn't archive First. Try again.")).toBeInTheDocument();
    });

    it("a failed archive leaves focus on the row's menu button", async () => {
      const archive = vi.fn().mockRejectedValue(new Error("x"));
      render(page({ list: [thread("a", "First")] }, { archive }));
      await chooseAction("First", "Archive");
      await screen.findByText("Couldn't archive First. Try again.");
      expect(screen.getByRole("status")).not.toHaveFocus();
    });

    it("a failed restore says so", async () => {
      const restore = vi.fn().mockRejectedValue(new Error("x"));
      render(page({ list: [] }, { restore, loadArchived: vi.fn().mockResolvedValue([thread("c", "Old")]) }));
      await userEvent.click(await screen.findByRole("tab", { name: /^Archived\s*1$/ }));
      await chooseAction("Old", "Restore");
      expect(await screen.findByText("Couldn't restore Old. Try again.")).toBeInTheDocument();
    });

    it("an empty Active list still invites a conversation when the archived load fails", async () => {
      render(page({ list: [] }, { loadArchived: vi.fn().mockRejectedValue(new Error("x")) }));
      expect(await screen.findByRole("heading", { name: "No conversations yet" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Start a conversation" })).toBeInTheDocument();
    });

    it("the Archived tab says so when the archived list can't load", async () => {
      render(page({ list: [thread("a", "First")] }, { loadArchived: vi.fn().mockRejectedValue(new Error("x")) }));
      await userEvent.click(await screen.findByRole("tab", { name: /^Archived/ }));
      expect(await screen.findByText("Can't load your archived conversations. Reload the page to try again.")).toBeInTheDocument();
    });

    it("an expired session says nothing", async () => {
      const archive = vi.fn().mockRejectedValue(new SessionExpiredError());
      const loadArchived = vi.fn().mockResolvedValue([]);
      render(page({ list: [thread("a", "First")] }, { archive, loadArchived }));
      await chooseAction("First", "Archive");
      await waitFor(() => expect(loadArchived).toHaveBeenCalledTimes(2));
      expect(screen.getByRole("status")).toHaveTextContent("");
    });
  });
});
