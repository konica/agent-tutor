import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentDetails } from "../../api/documents";
import { DocumentDetailsPanel } from "./DocumentDetails";

function details(over: Partial<DocumentDetails> = {}): DocumentDetails {
  return {
    document_id: "d1",
    state: "ready",
    archived: false,
    title: "ReAct",
    extracted_title: "ReAct",
    title_overridden: false,
    authors: ["Yao", "Zhao"],
    year: 2022,
    doi: "10.48550/arXiv.2210.03629",
    file_name: "react.pdf",
    pages: 33,
    summary: "Proposes prompting models to interleave reasoning and actions.",
    failure_reason: null,
    created_at: "2026-09-20T09:00:00Z",
    subjects: [{ subject_id: "s1", name: "AI Agents" }],
    attempt: null,
    max_attempts: 3,
    can_retry: false,
    ...over,
  };
}

function setup(first: DocumentDetails = details(), over: Partial<Parameters<typeof DocumentDetailsPanel>[0]> = {}) {
  const props = {
    documentId: "d1",
    load: vi.fn(async (_id: string) => first),
    saveTitle: vi.fn(async (_id: string, title: string | null) => details({ title: title ?? "ReAct", title_overridden: title !== null })),
    archive: vi.fn(async (_id: string) => ({})),
    restore: vi.fn(async (_id: string) => ({})),
    onChanged: vi.fn(),
    onClose: vi.fn(),
    ...over,
  };
  render(<DocumentDetailsPanel {...props} />);
  return props;
}

const field = () => screen.getByRole("textbox", { name: "Display title" });

describe("DocumentDetailsPanel", () => {
  it("shows the facts, summary and subjects of a ready document", async () => {
    setup();
    const dialog = await screen.findByRole("dialog", { name: "ReAct" });
    expect(dialog).toBeVisible();
    expect(screen.getByText("Document details")).toBeVisible();
    expect(screen.getByText("Ready")).toBeVisible();
    expect(screen.getByRole("heading", { name: "ReAct" })).toBeVisible();
    for (const [label, value] of [["Authors", "Yao, Zhao"], ["Year", "2022"], ["DOI", "10.48550/arXiv.2210.03629"], ["File name", "react.pdf"], ["Pages", "33"], ["Uploaded", new Date("2026-09-20T09:00:00Z").toLocaleDateString(undefined, { timeZone: "Asia/Ho_Chi_Minh", day: "numeric", month: "short", year: "numeric" })]]) {
      expect(screen.getByText(label!, { selector: "dt" }).nextElementSibling).toHaveTextContent(value!);
    }
    expect(screen.getByText("Proposes prompting models to interleave reasoning and actions.")).toBeVisible();
    expect(screen.getByText("AI Agents")).toBeVisible();
    expect(screen.getByRole("button", { name: "Edit title" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Archive" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();
    expect(screen.queryByRole("button", { name: /delete|download|open/i })).toBeNull();
  });

  it("edits the title, saves it and announces it", async () => {
    const user = userEvent.setup();
    const props = setup();
    await user.click(await screen.findByRole("button", { name: "Edit title" }));
    expect(field()).toHaveValue("ReAct");
    expect(field()).toHaveFocus();
    expect(screen.getByText("Only changes how the title appears to you. Citations use this title.")).toBeVisible();
    await user.clear(field());
    await user.type(field(), "ReAct (Yao et al.)");
    await user.click(screen.getByRole("button", { name: "Save title" }));
    expect(props.saveTitle).toHaveBeenCalledWith("d1", "ReAct (Yao et al.)");
    expect(await screen.findByRole("heading", { name: "ReAct (Yao et al.)" })).toBeVisible();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Title updated.");
    expect(props.onChanged).toHaveBeenCalled();
  });

  it("rejects an empty or too long title before saving", async () => {
    const user = userEvent.setup();
    const props = setup();
    await user.click(await screen.findByRole("button", { name: "Edit title" }));
    await user.clear(field());
    await user.keyboard("{Enter}");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a title");
    expect(props.saveTitle).not.toHaveBeenCalled();
    await user.click(field());
    await user.paste("a".repeat(301));
    await user.keyboard("{Enter}");
    expect(screen.getByRole("alert")).toHaveTextContent("Keep the title to 300 characters or fewer");
    expect(props.saveTitle).not.toHaveBeenCalled();
  });

  it("shows the server's message and stays in edit mode when saving fails", async () => {
    const user = userEvent.setup();
    setup(details(), { saveTitle: vi.fn(async () => { throw new Error("Enter a title"); }) });
    await user.click(await screen.findByRole("button", { name: "Edit title" }));
    await user.type(field(), "x");
    await user.click(screen.getByRole("button", { name: "Save title" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a title");
    expect(field()).toBeVisible();
  });

  it("resets an overridden title to the extracted one", async () => {
    const user = userEvent.setup();
    const props = setup(details({ title: "Mine", title_overridden: true }));
    expect(await screen.findByText(/Extracted title: ReAct/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Reset to extracted title" }));
    expect(props.saveTitle).toHaveBeenCalledWith("d1", null);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Title reset to the extracted title."));
  });

  it("offers reset in the edit form only when overridden", async () => {
    const user = userEvent.setup();
    setup(details({ title: "Mine", title_overridden: true }));
    await user.click(await screen.findByRole("button", { name: "Edit title" }));
    expect(screen.getByRole("button", { name: "Reset to extracted title" })).toBeVisible();
  });

  it("offers no reset when not overridden", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(await screen.findByRole("button", { name: "Edit title" }));
    expect(screen.queryByRole("button", { name: "Reset to extracted title" })).toBeNull();
  });

  it("offers no reset without an extracted title", async () => {
    setup(details({ title_overridden: true, extracted_title: null }));
    await screen.findByRole("heading", { name: "ReAct" });
    expect(screen.queryByRole("button", { name: "Reset to extracted title" })).toBeNull();
  });

  it("cancels editing on the first Escape and closes on the second", async () => {
    const user = userEvent.setup();
    const props = setup();
    await user.click(await screen.findByRole("button", { name: "Edit title" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("heading", { name: "ReAct" })).toBeVisible();
    expect(props.onClose).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("archives, reloads and shows the archived state", async () => {
    const user = userEvent.setup();
    const load = vi.fn().mockResolvedValueOnce(details()).mockResolvedValue(details({ archived: true }));
    const props = setup(details(), { load });
    await user.click(await screen.findByRole("button", { name: "Archive" }));
    expect(props.archive).toHaveBeenCalledWith("d1");
    expect(await screen.findByRole("button", { name: "Restore" })).toBeVisible();
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status")).toHaveTextContent("Document archived.");
    expect(props.onChanged).toHaveBeenCalled();
  });

  it("shows an archived document with a Restore action", async () => {
    const user = userEvent.setup();
    const load = vi.fn().mockResolvedValueOnce(details({ archived: true })).mockResolvedValue(details());
    const props = setup(details(), { load });
    expect(await screen.findByText("Not used for answers. Citations to it in past conversations still open here. Restore it to change its subjects.")).toBeVisible();
    expect(screen.getAllByText("Archived").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit title" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(props.restore).toHaveBeenCalledWith("d1");
    expect(await screen.findByRole("button", { name: "Archive" })).toBeVisible();
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status")).toHaveTextContent("Document restored.");
  });

  it("opens in edit mode with startEditing", async () => {
    setup(details(), { startEditing: true });
    await screen.findByRole("textbox", { name: "Display title" });
    await waitFor(() => expect(field()).toHaveFocus());
  });

  it("explains a missing summary and shows dashes for unknown facts", async () => {
    setup(details({ summary: null, authors: [], year: null, doi: null, pages: null, subjects: [] }));
    expect(await screen.findByText("A summary appears once Smart Tutor can read this PDF.")).toBeVisible();
    expect(screen.getAllByText("—")).toHaveLength(4);
    expect(screen.getByText("No subjects yet.")).toBeVisible();
  });

  it("shows why a failed document failed and cannot be renamed", async () => {
    setup(details({ state: "failed", failure_reason: "This PDF has no text." }));
    expect(await screen.findByText("This PDF has no text.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Edit title" })).toBeNull();
  });

  it("says so when the document can't be loaded and still closes", async () => {
    const user = userEvent.setup();
    const props = setup(details(), { load: vi.fn(async () => { throw new Error("boom"); }) });
    expect(await screen.findByText("Couldn't load this document.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Close document details" }));
    expect(props.onClose).toHaveBeenCalled();
  });
});
