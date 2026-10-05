import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentResponse } from "../../api/documents";
import { LibraryPage } from "./LibraryPage";

const today = new Date().toISOString();
const processing: DocumentResponse = { document_id: "d1", title: "lewis-rag-2020.pdf", state: "processing", failure_reason: null, created_at: today, subjects: [] };
const duplicate: DocumentResponse = { document_id: "d2", title: "copy.pdf", state: "failed", failure_reason: "Duplicate uploads aren't supported yet", created_at: today, subjects: [] };

afterEach(() => vi.useRealTimers());

describe("LibraryPage", () => {
  it("shows the first-run card when the library is empty", async () => {
    render(<LibraryPage load={async () => []} upload={vi.fn()} />);
    expect(await screen.findByText("Upload your first document")).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose PDFs" })).toBeEnabled();
  });

  it("lists a processing document by its file name with the subjects hint", async () => {
    render(<LibraryPage load={async () => [processing]} upload={vi.fn()} />);
    const row = (await screen.findByText("lewis-rag-2020.pdf")).closest("tr")!;
    expect(within(row).getByText("Processing")).toBeVisible();
    expect(within(row).getByText("Not chosen yet")).toBeVisible();
    expect(within(row).getByText("You can choose subjects when processing finishes.")).toBeVisible();
    expect(within(row).getByText("Today")).toBeVisible();
  });

  it("shows a ready document's subjects by name", async () => {
    const ready: DocumentResponse = { ...processing, state: "ready", subjects: [{ subject_id: "s1", name: "General" }] };
    render(<LibraryPage load={async () => [ready]} upload={vi.fn()} />);
    const row = (await screen.findByText("lewis-rag-2020.pdf")).closest("tr")!;
    expect(within(row).getByText("General")).toBeVisible();
    expect(within(row).queryByText("Not chosen yet")).toBeNull();
    expect(within(row).queryByText("You can choose subjects when processing finishes.")).toBeNull();
  });

  it("shows a failed document's reason", async () => {
    render(<LibraryPage load={async () => [duplicate]} upload={vi.fn()} />);
    const row = (await screen.findByText("copy.pdf")).closest("tr")!;
    expect(within(row).getByText("Failed")).toBeVisible();
    expect(within(row).getByText("Duplicate uploads aren't supported yet")).toBeVisible();
  });

  it("uploads the picked PDF and refreshes the list", async () => {
    const load = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([processing]);
    const upload = vi.fn(async () => {});
    render(<LibraryPage load={load} upload={upload} />);
    await screen.findByText("Upload your first document");
    const file = new File(["%PDF"], "lewis-rag-2020.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), file);
    expect(upload).toHaveBeenCalledWith(file);
    expect(screen.getByRole("status")).toHaveTextContent(/Uploading lewis-rag-2020.pdf…|Uploaded lewis-rag-2020.pdf. Processing./);
    expect(await screen.findByText("lewis-rag-2020.pdf")).toBeVisible();
  });

  it("shows an error when the upload fails", async () => {
    const upload = vi.fn(async () => {
      throw new Error("Upload to storage failed (403)");
    });
    render(<LibraryPage load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "big.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("Couldn't upload big.pdf. Try again.")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Upload failed: big.pdf.");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("refuses an oversized file in the browser: no API call, same message and announcement", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    render(<LibraryPage load={async () => []} />);
    await screen.findByText("Upload your first document");
    const big = new File(["x"], "huge.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 52_428_801 });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), big);
    expect(await screen.findByText("Couldn't upload huge.pdf. Try again.")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Upload failed: huge.pdf.");
    expect(fetch).not.toHaveBeenCalled();
    fetch.mockRestore();
  });

  it("announces a processing state change in the status region, but not the first load", async () => {
    const failedNow: DocumentResponse = { ...processing, state: "failed", failure_reason: "Duplicate uploads aren't supported yet" };
    const load = vi.fn().mockResolvedValueOnce([processing]).mockResolvedValue([failedNow]);
    render(<LibraryPage load={load} upload={vi.fn()} pollMs={20} />);
    await screen.findByText("Processing");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("lewis-rag-2020.pdf failed: Duplicate uploads aren't supported yet."),
    );
  });

  it("refreshes every 2 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const load = vi.fn(async () => [processing]);
    render(<LibraryPage load={load} upload={vi.fn()} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4100);
    });
    expect(load.mock.calls.length).toBeGreaterThanOrEqual(3);
  });
});
