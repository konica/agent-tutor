import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { ThreadDocumentResponse } from "../../api/generated/types.gen";
import { ConversationPanel } from "./ConversationPanel";

const used = (title: string, extra: Partial<ThreadDocumentResponse> = {}): ThreadDocumentResponse => ({
  document_id: title,
  title,
  authors: [],
  year: null,
  archived: false,
  added_by: "answer",
  used: true,
  deleted: false,
  ...extra,
});

function renderPanel(props: Partial<ComponentProps<typeof ConversationPanel>> = {}) {
  const onShowCitationsChange = vi.fn();
  render(
    <ConversationPanel
      id="conversation-panel"
      documents={[]}
      threadId={null}
      answered={false}
      showCitations
      onShowCitationsChange={onShowCitationsChange}
      searchListed={false}
      {...props}
    />,
  );
  return { onShowCitationsChange };
}

const documentsSection = () => screen.getByRole("region", { name: /^Documents/ });

describe("ConversationPanel", () => {
  it("says where documents used will appear, with a zero count, before any answer", () => {
    renderPanel();
    expect(screen.getByText("Documents used to answer will appear here.")).toBeInTheDocument();
    expect(within(documentsSection()).getByText("0")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Documents/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Lesson Note" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Actions" })).toBeInTheDocument();
    expect(screen.getByText("After the first answer you can summarize this conversation into a note.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Summarize lesson" })).not.toBeInTheDocument();
  });

  it("says the documents used couldn't be loaded, without a count, when they failed", () => {
    renderPanel({ answered: true, documentsFailed: true });
    expect(within(documentsSection()).getByText("Couldn't load the documents used.")).toBeInTheDocument();
    expect(within(documentsSection()).queryByText("0")).not.toBeInTheDocument();
    expect(screen.queryByText("Documents used to answer will appear here.")).not.toBeInTheDocument();
  });

  it("lists the documents used in the given order, marking archived and deleted ones", () => {
    renderPanel({
      answered: true,
      onRemoveDocument: vi.fn(),
      documents: [
        used("ReAct", { authors: ["Yao", "Zhao"], year: 2023 }),
        used("RAG", { archived: true }),
        used("PPO", { deleted: true }),
      ],
    });
    const rows = within(documentsSection()).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual(["ReAct", "RAGArchived", "PPODeleted"]);
    expect(rows[0]).toHaveAttribute("title", "ReAct\nYao, Zhao · 2023");
    expect(within(documentsSection()).getByText("3")).toBeInTheDocument();
    expect(screen.queryByText("Documents used to answer will appear here.")).not.toBeInTheDocument();
    // Opening a document from a row comes with #123: a row's only button removes it.
    expect(within(rows[0]!).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "Remove ReAct from this conversation",
    ]);
  });

  it("offers Add documents once the conversation exists", async () => {
    const onAddDocuments = vi.fn();
    renderPanel({ threadId: "t1", onAddDocuments });
    const add = within(documentsSection()).getByRole("button", { name: "Add documents" });
    expect(add).toHaveAttribute("aria-haspopup", "dialog");
    await userEvent.click(add);
    expect(onAddDocuments).toHaveBeenCalled();
  });

  it("offers no Add documents before there is a conversation", () => {
    renderPanel({ threadId: null, onAddDocuments: vi.fn() });
    expect(screen.queryByRole("button", { name: "Add documents" })).not.toBeInTheDocument();
  });

  it("marks a document the learner added that no answer has used yet", () => {
    renderPanel({
      threadId: "t1",
      answered: true,
      documents: [
        used("ReAct"),
        used("RAG", { added_by: "learner", used: false }),
        used("PPO", { added_by: "learner", used: true }),
        used("Gone", { added_by: "learner", used: false, deleted: true }),
      ],
    });
    const rows = within(documentsSection()).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual(["ReAct", "RAGAdded", "PPO", "GoneDeleted"]);
  });

  it("removes a row, deleted ones too, with its remove button", async () => {
    const onRemoveDocument = vi.fn();
    renderPanel({ threadId: "t1", documents: [used("ReAct"), used("PPO", { deleted: true })], onRemoveDocument });
    const remove = screen.getByRole("button", { name: "Remove PPO from this conversation" });
    expect(remove).toHaveAttribute("data-tip", "Remove from this conversation");
    await userEvent.click(remove);
    expect(onRemoveDocument).toHaveBeenCalledWith("PPO");
    await userEvent.click(screen.getByRole("button", { name: "Remove ReAct from this conversation" }));
    expect(onRemoveDocument).toHaveBeenCalledWith("ReAct");
  });

  describe("focus after removing a row", () => {
    function setup(documents: ThreadDocumentResponse[]) {
      const onRemoveDocument = vi.fn();
      const props = {
        id: "conversation-panel",
        threadId: "t1",
        answered: true,
        showCitations: true,
        onShowCitationsChange: vi.fn(),
        searchListed: false,
        onAddDocuments: vi.fn(),
        onRemoveDocument,
      };
      const view = render(<ConversationPanel {...props} documents={documents} />);
      const rerender = (next: ThreadDocumentResponse[]) => view.rerender(<ConversationPanel {...props} documents={next} />);
      return { rerender, onRemoveDocument };
    }
    const removeButton = (title: string) => screen.getByRole("button", { name: `Remove ${title} from this conversation` });

    it("moves to the previous row when the last row goes", async () => {
      const { rerender } = setup([used("a"), used("b")]);
      await userEvent.click(removeButton("b"));
      rerender([used("a")]);
      expect(removeButton("a")).toHaveFocus();
    });

    it("moves to the next row", async () => {
      const { rerender } = setup([used("a"), used("b")]);
      await userEvent.click(removeButton("a"));
      rerender([used("b")]);
      expect(removeButton("b")).toHaveFocus();
    });

    it("moves to Add documents when no row is left, and the empty text comes back", async () => {
      const { rerender } = setup([used("a")]);
      await userEvent.click(removeButton("a"));
      rerender([]);
      expect(screen.getByRole("button", { name: "Add documents" })).toHaveFocus();
      expect(screen.getByText("Documents used to answer will appear here.")).toBeInTheDocument();
    });

    it("stays put while the removed row is still listed", async () => {
      const { rerender, onRemoveDocument } = setup([used("a"), used("b")]);
      await userEvent.click(removeButton("a"));
      expect(onRemoveDocument).toHaveBeenCalledWith("a");
      rerender([used("a"), used("b")]);
      expect(removeButton("a")).toHaveFocus();
    });
  });

  it("marks a deleted document with an icon badge, no link, and one note below the list", () => {
    const { rerender } = render(
      <ConversationPanel
        id="p"
        documents={[used("A"), used("B", { deleted: true }), used("C", { deleted: true })]}
        threadId={null}
        answered
        showCitations
        onShowCitationsChange={vi.fn()}
        searchListed={false}
      />,
    );
    const row = within(documentsSection()).getAllByRole("listitem")[1];
    const badge = within(row).getByText("Deleted");
    expect(badge.querySelector("svg")).not.toBeNull();
    expect(within(row).queryByRole("link")).not.toBeInTheDocument();
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getAllByText("Deleted documents can't be opened.")).toHaveLength(1);

    rerender(
      <ConversationPanel
        id="p"
        documents={[used("A"), used("R", { archived: true })]}
        threadId={null}
        answered
        showCitations
        onShowCitationsChange={vi.fn()}
        searchListed={false}
      />,
    );
    expect(screen.queryByText("Deleted documents can't be opened.")).not.toBeInTheDocument();
  });

  it("offers a disabled Summarize lesson after the first answer", () => {
    renderPanel({ answered: true });
    expect(screen.getByText("Turn this conversation into a note you can edit.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Summarize lesson" })).toBeDisabled();
  });

  it("offers a disabled Archive conversation once the conversation exists, even before its answer", () => {
    renderPanel({ threadId: "t1", answered: false });
    expect(screen.getByRole("button", { name: "Archive conversation" })).toBeDisabled();
  });

  it("offers no Archive conversation before there is a conversation", () => {
    renderPanel({ threadId: null });
    expect(screen.queryByRole("button", { name: "Archive conversation" })).not.toBeInTheDocument();
  });

  describe("Only search these documents", () => {
    const scopeSwitch = () => screen.getByRole("switch", { name: "Only search these documents" });

    it("is off by default and disabled while the list is empty, saying why", () => {
      renderPanel({ threadId: "t1", searchListed: false, onSearchListedChange: vi.fn() });
      expect(scopeSwitch()).toHaveAttribute("aria-checked", "false");
      expect(scopeSwitch()).toBeDisabled();
      expect(scopeSwitch()).toHaveAccessibleDescription("Add documents to limit the search.");
      expect(within(documentsSection()).getByText("Add documents to limit the search.")).toBeInTheDocument();
    });

    it("turns the limit on", async () => {
      const onSearchListedChange = vi.fn();
      renderPanel({ threadId: "t1", documents: [used("ReAct")], searchListed: false, onSearchListedChange });
      expect(screen.queryByText("Add documents to limit the search.")).not.toBeInTheDocument();
      expect(scopeSwitch()).not.toHaveAccessibleDescription();
      await userEvent.click(scopeSwitch());
      expect(onSearchListedChange).toHaveBeenCalledWith(true);
    });

    it("turns the limit off", async () => {
      const onSearchListedChange = vi.fn();
      renderPanel({ threadId: "t1", documents: [used("ReAct")], searchListed: true, onSearchListedChange });
      expect(scopeSwitch()).toHaveAttribute("aria-checked", "true");
      await userEvent.click(scopeSwitch());
      expect(onSearchListedChange).toHaveBeenCalledWith(false);
    });

    it("sits under Add documents", () => {
      renderPanel({ threadId: "t1", documents: [used("ReAct")], searchListed: false, onAddDocuments: vi.fn(), onSearchListedChange: vi.fn() });
      const add = within(documentsSection()).getByRole("button", { name: "Add documents" });
      expect(add.compareDocumentPosition(scopeSwitch()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("is disabled before there is a conversation, and when the documents couldn't be loaded", () => {
      const { unmount } = render(
        <ConversationPanel id="p" documents={[used("ReAct")]} threadId={null} answered={false} showCitations onShowCitationsChange={vi.fn()} searchListed={false} />,
      );
      expect(scopeSwitch()).toBeDisabled();
      unmount();
      renderPanel({ threadId: "t1", documentsFailed: true, searchListed: false, onSearchListedChange: vi.fn() });
      expect(scopeSwitch()).toBeDisabled();
    });
  });

  it("turns citations off with the switch", async () => {
    const { onShowCitationsChange } = renderPanel();
    const toggle = screen.getByRole("switch", { name: "Show citations" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    await userEvent.click(toggle);
    expect(onShowCitationsChange).toHaveBeenCalledWith(false);
  });

  it("turns citations back on", async () => {
    const { onShowCitationsChange } = renderPanel({ showCitations: false });
    const toggle = screen.getByRole("switch", { name: "Show citations" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    expect(onShowCitationsChange).toHaveBeenCalledWith(true);
  });
});
