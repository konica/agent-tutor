import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentResponse } from "../../api/documents";
import { LibraryPage } from "./LibraryPage";

const today = new Date().toISOString();
const processing: DocumentResponse = { document_id: "d1", title: "lewis-rag-2020.pdf", state: "processing", failure_reason: null, created_at: today, subjects: [] };
const duplicate: DocumentResponse = { document_id: "d2", title: "copy.pdf", state: "failed", failure_reason: "Duplicate uploads aren't supported yet", created_at: today, subjects: [] };

const notInLibrary = async () => null;
const limits = async () => ({ max_bytes: 52_428_800, max_pages: 500 });

afterEach(() => vi.useRealTimers());

describe("LibraryPage", () => {
  it("shows the first-run card when the library is empty", async () => {
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={vi.fn()} />);
    expect(await screen.findByText("Upload your first document")).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose PDFs" })).toBeEnabled();
  });

  it("lists a processing document by its file name with the subjects hint", async () => {
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={vi.fn()} />);
    const row = (await screen.findByText("lewis-rag-2020.pdf")).closest("tr")!;
    expect(within(row).getByText("Processing")).toBeVisible();
    expect(within(row).getByText("Not chosen yet")).toBeVisible();
    expect(within(row).getByText("You can choose subjects when processing finishes.")).toBeVisible();
    expect(within(row).getByText("Today")).toBeVisible();
  });

  it("shows a ready document's subjects by name", async () => {
    const ready: DocumentResponse = { ...processing, state: "ready", subjects: [{ subject_id: "s1", name: "General" }] };
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => [ready]} upload={vi.fn()} />);
    const row = (await screen.findByText("lewis-rag-2020.pdf")).closest("tr")!;
    expect(within(row).getByText("General")).toBeVisible();
    expect(within(row).queryByText("Not chosen yet")).toBeNull();
    expect(within(row).queryByText("You can choose subjects when processing finishes.")).toBeNull();
  });

  it("shows a failed document's reason", async () => {
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => [duplicate]} upload={vi.fn()} />);
    const row = (await screen.findByText("copy.pdf")).closest("tr")!;
    expect(within(row).getByText("Failed")).toBeVisible();
    expect(within(row).getByText("Duplicate uploads aren't supported yet")).toBeVisible();
  });

  it("uploads the picked PDF and refreshes the list", async () => {
    const load = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([processing]);
    const upload = vi.fn(async () => {});
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={load} upload={upload} />);
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
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "big.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("Couldn't upload big.pdf. Try again.")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Upload failed: big.pdf.");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("refuses a non-PDF and an oversized file in the browser, uploads the rest, and says why", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage check={notInLibrary} load={async () => []} upload={upload} loadLimits={limits} />);
    await screen.findByText("Upload your first document");
    const docx = new File(["x"], "reading-list.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
    const big = new File(["x"], "deep-learning-book-full.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 72 * 1_048_576 });
    const good = new File(["%PDF"], "paper.pdf", { type: "application/pdf" });

    await userEvent.upload(screen.getByLabelText("Upload PDFs"), [docx, big, good], { applyAccept: false });

    expect(await screen.findByText("Not uploaded. Only PDF files can be uploaded.")).toBeVisible();
    expect(screen.getByText("reading-list.docx")).toBeVisible();
    expect(screen.getByText("Not uploaded. This file is 72 MB; the limit is 50 MB.")).toBeVisible();
    expect(upload).toHaveBeenCalledTimes(1);
    expect(upload).toHaveBeenCalledWith(good);
  });

  it("announces every refusal reason and the upload in the one status region", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage check={notInLibrary} load={async () => []} upload={upload} loadLimits={limits} />);
    await screen.findByText("Upload your first document");
    const docx = new File(["x"], "reading-list.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
    const big = new File(["x"], "deep-learning-book-full.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 72 * 1_048_576 });
    const good = new File(["%PDF"], "paper.pdf", { type: "application/pdf" });

    await userEvent.upload(screen.getByLabelText("Upload PDFs"), [docx, big, good], { applyAccept: false });

    const status = screen.getByRole("status");
    await waitFor(() => expect(status).toHaveTextContent("Uploaded paper.pdf. Processing."));
    expect(status).toHaveTextContent("reading-list.docx: Not uploaded. Only PDF files can be uploaded.");
    expect(status).toHaveTextContent("deep-learning-book-full.pdf: Not uploaded. This file is 72 MB; the limit is 50 MB.");
  });

  it("refuses a non-PDF with its reason even when the limits can't be loaded", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage check={notInLibrary} load={async () => []} upload={upload} loadLimits={async () => { throw new Error("down"); }} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "notes.docx", { type: "application/msword" }), { applyAccept: false });
    expect(await screen.findByText("Not uploaded. Only PDF files can be uploaded.")).toBeVisible();
    expect(screen.queryByText(/Couldn't upload/)).toBeNull();
    expect(upload).not.toHaveBeenCalled();
  });

  it("loads the limits once when the loader is an inline function", async () => {
    const loadLimits = vi.fn(limits);
    const { rerender } = render(<LibraryPage check={notInLibrary} load={async () => []} upload={vi.fn()} loadLimits={() => loadLimits()} />);
    await screen.findByText(/PDFs up to 50 MB/);
    rerender(<LibraryPage check={notInLibrary} load={async () => []} upload={vi.fn()} loadLimits={() => loadLimits()} />);
    expect(loadLimits).toHaveBeenCalledTimes(1);
  });

  it("makes no request at all for a refused file", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const upload = vi.fn(async () => {});
    render(<LibraryPage check={notInLibrary} load={async () => []} upload={upload} loadLimits={limits} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "a.txt", { type: "text/plain" }), { applyAccept: false });
    expect(await screen.findByText("Not uploaded. Only PDF files can be uploaded.")).toBeVisible();
    expect(upload).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    fetch.mockRestore();
  });

  it("states the limits from settings in the first-run card", async () => {
    render(<LibraryPage check={notInLibrary} load={async () => []} upload={vi.fn()} loadLimits={async () => ({ max_bytes: 10 * 1_048_576, max_pages: 200 })} />);
    expect(await screen.findByText(/PDFs up to 10 MB and 200 pages/)).toBeVisible();
  });

  it("never uploads when the limits can't be loaded", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage check={notInLibrary} load={async () => []} upload={upload} loadLimits={async () => { throw new Error("down"); }} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["%PDF"], "paper.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("Couldn't upload paper.pdf. Try again.")).toBeVisible();
    expect(upload).not.toHaveBeenCalled();
  });

  it("announces a processing state change in the status region, but not the first load", async () => {
    const failedNow: DocumentResponse = { ...processing, state: "failed", failure_reason: "Duplicate uploads aren't supported yet" };
    const load = vi.fn().mockResolvedValueOnce([processing]).mockResolvedValue([failedNow]);
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} pollMs={20} />);
    await screen.findByText("Processing");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("lewis-rag-2020.pdf failed: Duplicate uploads aren't supported yet."),
    );
  });

  it("refreshes every 2 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const load = vi.fn(async () => [processing]);
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4100);
    });
    expect(load.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("skips the upload of a file already in the library and links to its row", async () => {
    const upload = vi.fn(async () => {});
    const check = vi.fn(async () => "d1");
    render(<LibraryPage loadLimits={limits} load={async () => [processing]} upload={upload} check={check} />);
    await screen.findByText("lewis-rag-2020.pdf");
    const file = new File(["%PDF"], "lewis-rag-2020.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), file);
    const list = await screen.findByRole("list", { name: "Already in your library" });
    expect(within(list).getByText("lewis-rag-2020.pdf")).toBeVisible();
    expect(within(list).getByText("Already in your library")).toBeVisible();
    expect(within(list).getByRole("link", { name: "Open document" })).toHaveAttribute("href", "#document-d1");
    expect(upload).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("lewis-rag-2020.pdf: Already in your library.");
    expect(document.getElementById("document-d1")).not.toBeNull();
  });

  it("uploads only the files not already in the library", async () => {
    const upload = vi.fn(async () => {});
    const check = vi.fn(async (f: File) => (f.name === "have.pdf" ? "d1" : null));
    render(<LibraryPage loadLimits={limits} load={async () => [processing]} upload={upload} check={check} />);
    await screen.findByText("lewis-rag-2020.pdf");
    const have = new File(["%PDF a"], "have.pdf", { type: "application/pdf" });
    const fresh = new File(["%PDF b"], "fresh.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), [have, fresh]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(upload).toHaveBeenCalledWith(fresh);
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("have.pdf: Already in your library. Uploaded fresh.pdf. Processing."),
    );
  });

  it("uploads anyway when the check fails", async () => {
    const upload = vi.fn(async () => {});
    const check = vi.fn(async () => {
      throw new Error("500");
    });
    render(<LibraryPage loadLimits={limits} load={async () => []} upload={upload} check={check} />);
    await screen.findByText("Upload your first document");
    const file = new File(["%PDF"], "x.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), file);
    await waitFor(() => expect(upload).toHaveBeenCalledWith(file));
  });

  it("does not check a rejected file", async () => {
    const check = vi.fn(async () => null);
    render(<LibraryPage loadLimits={limits} load={async () => []} upload={vi.fn()} check={check} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "notes.docx", { type: "application/msword" }), { applyAccept: false });
    expect(check).not.toHaveBeenCalled();
  });
});

describe("LibraryPage choose subjects", () => {
  const waiting: DocumentResponse = { ...processing, title: "Toolformer", state: "awaiting_subjects" };
  const suggestions = {
    document_id: "d1",
    title: "Toolformer",
    summary: null,
    suggestions: [{ subject_id: "s1", name: "AI Agents", origin: "yours" as const }],
  };

  // The picker's banner is also a status; the page's live region is the one in the document body.
  const pageStatus = () => screen.getAllByRole("status").find((el) => el.tagName === "P")!;

  it("offers the action only on a document waiting for subjects", async () => {
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => [waiting, duplicate, processing]} upload={vi.fn()} />);
    const row = (await screen.findByText("Toolformer")).closest("tr")!;
    expect(within(row).getAllByText("Choose subjects")).toHaveLength(2); // the badge and the button label
    expect(within(row).getByRole("button", { name: "Choose subjects for Toolformer" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: /^Choose subjects for/ })).toHaveLength(1);
  });

  it("opens the picker, saves, announces it and reloads", async () => {
    const ready: DocumentResponse = { ...waiting, state: "ready", subjects: [{ subject_id: "s1", name: "AI Agents" }] };
    const load = vi.fn().mockResolvedValueOnce([waiting]).mockResolvedValue([ready]);
    const loadSuggestions = vi.fn(async () => suggestions);
    const saveSubjects = vi.fn(async () => ready);
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} loadSuggestions={loadSuggestions} saveSubjects={saveSubjects} />);
    await userEvent.click(await screen.findByRole("button", { name: "Choose subjects for Toolformer" }));
    expect(screen.getByRole("dialog", { name: "Choose subjects" })).toBeVisible();
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect(saveSubjects).toHaveBeenCalledWith("d1", { subject_ids: ["s1"], new_names: [] });
    await waitFor(() => expect(pageStatus()).toHaveTextContent("Subjects saved. Toolformer is ready to use."));
    expect(load).toHaveBeenCalledTimes(2);
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(pageStatus()).toHaveFocus();
    expect((await screen.findByText("Toolformer")).closest("tr")).toHaveTextContent("AI Agents");
  });
});
