import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentResponse } from "../../api/documents";
import { DocumentTable } from "./DocumentTable";

const doc: DocumentResponse = { document_id: "d1", title: "Toolformer", state: "ready", failure_reason: null, created_at: "2026-10-04T09:00:00Z", subjects: [], attempt: null, max_attempts: 3, can_retry: false, authors: ["Timo Schick", "Jane Dwivedi-Yu", "Roberto Dessì"], year: 2023, archived: false };

describe("DocumentTable", () => {
  afterEach(() => vi.useRealTimers());

  it("shows authors and year under the title", () => {
    render(<DocumentTable documents={[doc]} onRetry={() => {}} retrying={new Set()} />);
    const row = screen.getByText("Toolformer").closest("tr")!;
    expect(within(row).getByText("Schick et al. · 2023")).toBeVisible();
  });

  it("shows no byline when authors and year are missing", () => {
    render(<DocumentTable documents={[{ ...doc, authors: [], year: null }]} onRetry={() => {}} retrying={new Set()} />);
    const cell = screen.getByText("Toolformer").closest("td")!;
    expect(cell).toHaveTextContent(/^Toolformer$/);
  });
});

describe("DocumentTable compact rows", () => {
  const props = { onRetry: () => {}, retrying: new Set<string>() };

  it("keeps a row on one line: authors and year inline, the full title in the tooltip", () => {
    const long = "Toolformer: Language Models Can Teach Themselves to Use Tools";
    render(<DocumentTable documents={[{ ...doc, title: long, authors: ["Schick", "Dwivedi-Yu"], year: 2023 }]} {...props} />);
    const title = screen.getByText(long);
    expect(title).toHaveAttribute("title", long);
    expect(title.closest("td")).toHaveTextContent(/Schick/);
  });

  it("gives the byline and the subjects their full text as a tooltip", () => {
    const subjects = [{ subject_id: "s1", name: "AI Agents" }, { subject_id: "s2", name: "LLMs" }];
    render(<DocumentTable documents={[{ ...doc, subjects }]} {...props} />);
    expect(screen.getByText("Schick et al. · 2023")).toHaveAttribute("title", "Schick et al. · 2023");
    expect(screen.getByText("AI Agents").closest("div")).toHaveAttribute("title", "AI Agents, LLMs");
  });

  it("shows the year for an upload from a past year", () => {
    vi.useFakeTimers({ now: new Date("2026-10-20T00:00:00Z") });
    render(<DocumentTable documents={[{ ...doc, created_at: "2025-03-05T09:00:00Z" }]} {...props} />);
    expect(screen.getByRole("cell", { name: /2025/ })).toBeVisible();
  });

  it("puts the processing hint on the badge line with the full hint as its tooltip", () => {
    render(<DocumentTable documents={[{ ...doc, state: "processing" }]} {...props} />);
    const hint = "You can choose subjects when processing finishes.";
    expect(screen.getByText(hint)).toHaveAttribute("title", hint);
  });

  it("shows a failure reason in full", () => {
    const reason = "No text layer (scanned PDFs are not supported yet)";
    render(<DocumentTable documents={[{ ...doc, state: "failed", failure_reason: reason, can_retry: true }]} {...props} />);
    expect(screen.getByText(reason)).not.toHaveAttribute("title");
  });
});

describe("DocumentTable upload day", () => {
  afterEach(() => vi.useRealTimers());

  it("shows the day in GMT+7, not the browser's", () => {
    vi.useFakeTimers({ now: new Date("2026-10-20T00:00:00Z") });
    render(<DocumentTable documents={[{ ...doc, created_at: "2026-10-01T17:30:00Z" }]} onRetry={() => {}} retrying={new Set()} />);
    expect(screen.getByRole("cell", { name: /2 Oct|Oct 2/ })).toBeVisible();
  });

  it("says Today when the upload is on the current GMT+7 day", () => {
    vi.useFakeTimers({ now: new Date("2026-10-02T01:00:00Z") });
    render(<DocumentTable documents={[{ ...doc, created_at: "2026-10-01T17:30:00Z" }]} onRetry={() => {}} retrying={new Set()} />);
    expect(screen.getByText("Today")).toBeVisible();
  });
});

describe("DocumentTable archive and restore", () => {
  const props = { onRetry: () => {}, retrying: new Set<string>() };

  it("gives an active row a More menu with Archive", async () => {
    const onArchive = vi.fn();
    render(<DocumentTable documents={[doc]} {...props} onArchive={onArchive} onRestore={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "More actions for Toolformer" }));
    const menu = screen.getByRole("menu", { name: "More actions for Toolformer" });
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Archive"]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Archive" }));
    expect(onArchive).toHaveBeenCalledExactlyOnceWith(doc);
  });

  it("lists Delete… after Archive in a ready row's menu and calls onDelete", async () => {
    const onDelete = vi.fn();
    render(<DocumentTable documents={[doc]} {...props} onArchive={vi.fn()} onDelete={onDelete} />);
    await userEvent.click(screen.getByRole("button", { name: "More actions for Toolformer" }));
    const menu = screen.getByRole("menu", { name: "More actions for Toolformer" });
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Archive", "Delete…"]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Delete…" }));
    expect(onDelete).toHaveBeenCalledExactlyOnceWith(doc);
  });

  it("offers no Delete… while a document is processing", async () => {
    render(<DocumentTable documents={[{ ...doc, state: "processing" }]} {...props} onArchive={vi.fn()} onDelete={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "More actions for Toolformer" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Archive"]);
  });

  it("offers an archived processing row Restore and no More menu", () => {
    render(<DocumentTable documents={[{ ...doc, state: "processing", archived: true }]} {...props} onRestore={vi.fn()} onDelete={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Restore Toolformer" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "More actions for Toolformer" })).toBeNull();
  });

  it("gives an archived row Restore and a More menu with only Delete…", async () => {
    const onDelete = vi.fn();
    const archived = { ...doc, archived: true };
    render(<DocumentTable documents={[archived]} {...props} onRestore={vi.fn()} onDelete={onDelete} />);
    const row = screen.getByText("Toolformer").closest("tr")!;
    expect(within(row).getByRole("button", { name: "Restore Toolformer" })).toBeVisible();
    await userEvent.click(within(row).getByRole("button", { name: "More actions for Toolformer" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Delete…"]);
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete…" }));
    expect(onDelete).toHaveBeenCalledExactlyOnceWith(archived);
  });

  it("gives a row still uploading no More menu", () => {
    render(<DocumentTable documents={[doc]} {...props} onArchive={vi.fn()} uploading={new Set(["d1"])} />);
    expect(screen.queryByRole("button", { name: "More actions for Toolformer" })).toBeNull();
  });

  it("gives an archived row the Archived badge and Restore, and no More or Choose subjects", async () => {
    const onRestore = vi.fn();
    const archived = { ...doc, state: "awaiting_subjects" as const, archived: true };
    render(<DocumentTable documents={[archived]} {...props} onArchive={vi.fn()} onRestore={onRestore} onChooseSubjects={vi.fn()} />);
    const row = screen.getByText("Toolformer").closest("tr")!;
    expect(within(row).getByText("Archived")).toBeVisible();
    expect(within(row).queryByRole("button", { name: /More actions/ })).toBeNull();
    expect(within(row).queryByRole("button", { name: /Choose subjects/ })).toBeNull();
    await userEvent.click(within(row).getByRole("button", { name: "Restore Toolformer" }));
    expect(onRestore).toHaveBeenCalledExactlyOnceWith(archived);
  });

  it("gives an archived failed row no Retry", () => {
    render(<DocumentTable documents={[{ ...doc, state: "failed", failure_reason: "x", can_retry: true, archived: true }]} {...props} onRestore={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("disables a busy row's buttons", () => {
    render(
      <DocumentTable
        documents={[doc, { ...doc, document_id: "d2", title: "Old", archived: true }]}
        {...props}
        onArchive={vi.fn()}
        onRestore={vi.fn()}
        busy={new Set(["d1", "d2"])}
      />,
    );
    expect(screen.getByRole("button", { name: "More actions for Toolformer" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restore Old" })).toBeDisabled();
  });
});
