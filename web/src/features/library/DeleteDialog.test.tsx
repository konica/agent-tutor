import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentResponse } from "../../api/documents";
import { DeleteDialog } from "./DeleteDialog";

const doc = (patch: Partial<DocumentResponse> = {}): DocumentResponse => ({
  document_id: "d1", title: "Chain-of-Thought Prompting", state: "ready", failure_reason: null, created_at: "2026-10-04T09:00:00Z",
  subjects: [], attempt: null, max_attempts: 3, can_retry: false, authors: [], year: null, archived: false, ...patch,
});

const setup = (props: Partial<Parameters<typeof DeleteDialog>[0]> = {}) => {
  const handlers = { onCancel: vi.fn(), onDelete: vi.fn(), onArchive: vi.fn() };
  render(<DeleteDialog doc={doc()} {...handlers} {...props} />);
  return handlers;
};

describe("DeleteDialog", () => {
  it("asks to confirm with Cancel focused, and offers Archive instead for an active document", () => {
    setup();
    expect(screen.getByRole("dialog", { name: "Delete Chain-of-Thought Prompting?" })).toBeInTheDocument();
    expect(screen.getByText("This can't be undone. Conversations and notes keep their text.")).toBeInTheDocument();
    expect(screen.getByText("Archive hides it and can be undone.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Archive instead" })).toBeInTheDocument();
  });

  it("has no Archive instead for an archived document", () => {
    setup({ doc: doc({ archived: true }) });
    expect(screen.queryByRole("button", { name: "Archive instead" })).toBeNull();
    expect(screen.queryByText("Archive hides it and can be undone.")).toBeNull();
  });

  it("calls onDelete, onArchive and onCancel from Delete, Archive instead, Cancel and Escape", async () => {
    const h = setup();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(h.onDelete).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Archive instead" }));
    expect(h.onArchive).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(h.onCancel).toHaveBeenCalledTimes(1);
    await userEvent.keyboard("{Escape}");
    expect(h.onCancel).toHaveBeenCalledTimes(2);
  });

  it("disables both actions while deleting", () => {
    setup({ busy: true });
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Archive instead" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
  });
});
