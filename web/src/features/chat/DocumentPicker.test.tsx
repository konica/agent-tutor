import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentResponse } from "../../api/documents";
import { DocumentPicker } from "./DocumentPicker";

const ready = (document_id: string, title: string, extra: Partial<DocumentResponse> = {}): DocumentResponse => ({
  document_id,
  title,
  state: "ready",
  failure_reason: null,
  created_at: new Date().toISOString(),
  subjects: [],
  attempt: 1,
  max_attempts: 3,
  can_retry: false,
  authors: [],
  year: null,
  archived: false,
  ...extra,
});

const docs = [
  ready("d1", "ReAct", { authors: ["Yao", "Zhao"], year: 2023 }),
  ready("d2", "Retrieval-Augmented Generation", { authors: ["Lewis"], year: 2020 }),
  ready("d3", "Toolformer"),
];

function setup(over: Partial<Parameters<typeof DocumentPicker>[0]> = {}) {
  const props = {
    listedIds: new Set(["d1"]) as ReadonlySet<string>,
    loadReady: vi.fn(async () => docs),
    onAdd: vi.fn(async (_ids: string[]) => {}),
    onClose: vi.fn(),
    ...over,
  };
  render(<DocumentPicker {...props} />);
  return props;
}

const list = () => screen.getByRole("list", { name: "Your ready documents" });
const box = (title: string) => screen.findByRole("checkbox", { name: new RegExp(`^${title}`) });
const addButton = () => screen.getByRole("button", { name: /^Add/ });

describe("DocumentPicker", () => {
  it("is a dialog named Add documents with the search box focused", async () => {
    setup();
    expect(screen.getByRole("dialog", { name: "Add documents" })).toBeInTheDocument();
    const search = screen.getByRole("searchbox", { name: "Search your documents" });
    expect(search).toHaveAttribute("placeholder", "Search your documents");
    expect(search).toHaveFocus();
    await box("ReAct");
  });

  it("lists the ready documents; a listed one is checked, fixed, and says it is in this conversation", async () => {
    setup();
    const listed = await box("ReAct");
    expect(listed).toBeChecked();
    expect(listed).toBeDisabled();
    const rows = within(list()).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      "ReActIn this conversation",
      "Retrieval-Augmented GenerationLewis · 2020",
      "Toolformer",
    ]);
    expect(await box("Toolformer")).not.toBeChecked();
    expect(await box("Toolformer")).toBeEnabled();
  });

  it("filters by title, ignoring case, and says when nothing matches", async () => {
    setup();
    await box("ReAct");
    const search = screen.getByRole("searchbox", { name: "Search your documents" });
    await userEvent.type(search, "TOOL");
    expect(within(list()).getAllByRole("listitem").map((r) => r.textContent)).toEqual(["Toolformer"]);
    await userEvent.clear(search);
    await userEvent.type(search, "zzz");
    expect(within(list()).getByText("No ready documents match.")).toBeInTheDocument();
  });

  it("adds the checked documents in list order, counting them on the button", async () => {
    const props = setup({ listedIds: new Set() });
    await box("ReAct");
    expect(addButton()).toHaveTextContent(/^Add$/);
    expect(addButton()).toBeDisabled();
    await userEvent.click(await box("Toolformer"));
    expect(addButton()).toHaveTextContent("Add 1 document");
    await userEvent.click(await box("ReAct"));
    expect(addButton()).toHaveTextContent("Add 2 documents");
    await userEvent.click(addButton());
    expect(props.onAdd).toHaveBeenCalledWith(["d1", "d3"]);
  });

  it("unchecking takes a document out of the selection", async () => {
    setup();
    await userEvent.click(await box("Toolformer"));
    await userEvent.click(await box("Toolformer"));
    expect(addButton()).toHaveTextContent(/^Add$/);
    expect(addButton()).toBeDisabled();
  });

  it("keeps the dialog and the selection and says so when adding fails", async () => {
    const props = setup({ onAdd: vi.fn(() => Promise.reject(new Error("500"))) });
    await userEvent.click(await box("Toolformer"));
    await userEvent.click(addButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't add the documents. Try again.");
    expect(screen.getByRole("dialog", { name: "Add documents" })).toBeInTheDocument();
    expect(await box("Toolformer")).toBeChecked();
    expect(addButton()).toBeEnabled();
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("says the documents couldn't be loaded", async () => {
    setup({ loadReady: vi.fn(() => Promise.reject(new Error("500"))) });
    expect(await screen.findByText("Your documents couldn't be loaded.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Your ready documents" })).not.toBeInTheDocument();
  });

  it("closes with Cancel", async () => {
    const props = setup();
    await box("ReAct");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(props.onClose).toHaveBeenCalled();
  });

  it("closes with Escape", async () => {
    const props = setup();
    await box("ReAct");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(props.onClose).toHaveBeenCalled());
  });

  it("stops at 50 selections: the other rows are disabled and a line says why", async () => {
    const many = Array.from({ length: 51 }, (_, i) => ready(`m${i}`, `Paper ${String(i).padStart(2, "0")}`));
    setup({ listedIds: new Set(), loadReady: vi.fn(async () => many) });
    await screen.findByText("Paper 00");
    // Role queries are slow on 51 rows: take the checkboxes once.
    const boxes = screen.getAllByRole("checkbox", { hidden: true });
    boxes.slice(0, 50).forEach((b) => fireEvent.click(b));
    expect(screen.getByText("You can add up to 50 documents at a time.")).toBeInTheDocument();
    expect(boxes[50]).toBeDisabled();
    expect(boxes[49]).toBeEnabled();
    expect(screen.getByText("Add 50 documents")).toBeInTheDocument();
  }, 20_000);
});
