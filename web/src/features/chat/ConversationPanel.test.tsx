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
    // Opening a document from a row comes with #123.
    expect(within(documentsSection()).queryByRole("button")).not.toBeInTheDocument();
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
