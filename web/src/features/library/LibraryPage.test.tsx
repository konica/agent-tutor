import { act, fireEvent, render as renderBare, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import { DocumentGoneError, DocumentProcessingError, RetriesUsedUpError, type DocumentFilters, type DocumentResponse, type UploadEvents, type UploadStatus } from "../../api/documents";
import { SessionExpiredError } from "../../auth/authClient";
import { NeedsSubjectsContext } from "../../app/needsSubjects";
import { LibraryPage } from "./LibraryPage";

// The page navigates (Chat on a row), so every render sits in a router.
const inRouter = (ui: React.ReactElement) => (
  <MemoryRouter initialEntries={["/library"]}>
    <Routes>
      <Route path="/library" element={ui} />
      <Route path="/chat" element={<ChatStub />} />
    </Routes>
  </MemoryRouter>
);
const render = (ui: React.ReactElement) => {
  const result = renderBare(inRouter(ui));
  return { ...result, rerender: (next: React.ReactElement) => result.rerender(inRouter(next)) };
};
function ChatStub() {
  const { pathname, search } = useLocation();
  return <p>{`${pathname}${search}`}</p>;
}

const today = new Date().toISOString();
const processing: DocumentResponse = { document_id: "d1", title: "lewis-rag-2020.pdf", state: "processing", failure_reason: null, created_at: today, subjects: [], attempt: null, max_attempts: 3, can_retry: false, authors: [], year: null, archived: false };
const duplicate: DocumentResponse = { document_id: "d2", title: "copy.pdf", state: "failed", failure_reason: "This file isn't a readable PDF", created_at: today, subjects: [], attempt: null, max_attempts: 3, can_retry: false, authors: [], year: null, archived: false };

const notInLibrary = async () => null;
const noSubjects = async () => [];
const limits = async () => ({ max_bytes: 52_428_800, max_pages: 500 });

afterEach(() => vi.useRealTimers());

describe("LibraryPage", () => {
  it("shows the first-run card when the library is empty", async () => {
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={vi.fn()} />);
    expect(await screen.findByText("Upload your first document")).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose PDFs" })).toBeEnabled();
    expect(screen.getByText("Only upload documents you have the right to use.")).toBeVisible();
    expect(screen.queryByText(/^0 documents$/, { selector: "span:not([aria-live])" })).toBeNull();
  });

  it("shows the upload-rights sentence beside Upload and the count in the header", async () => {
    const three = ["a", "b", "c"].map((n) => ({ ...processing, document_id: n, title: `${n}.pdf` }));
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => three} upload={vi.fn()} />);
    expect(await screen.findByText("3 active documents", { selector: "span:not([aria-live])" })).toBeVisible();
    expect(screen.getByText("Only upload documents you have the right to use.")).toBeVisible();
    expect(screen.getByRole("button", { name: "About Library" })).toHaveAttribute("data-tip", expect.stringContaining("private to you"));
  });

  it("lists a processing document by its file name with the subjects hint", async () => {
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={vi.fn()} />);
    const row = (await screen.findByText("lewis-rag-2020.pdf")).closest("tr")!;
    expect(within(row).getByText("Processing")).toBeVisible();
    expect(within(row).getByText("Not chosen yet")).toBeVisible();
    expect(within(row).getByText("You can choose subjects when processing finishes.")).toBeVisible();
    expect(within(row).getByText("Today")).toBeVisible();
  });

  it("shows a ready document's subjects by name", async () => {
    const ready: DocumentResponse = { ...processing, state: "ready", subjects: [{ subject_id: "s1", name: "General" }] };
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [ready]} upload={vi.fn()} />);
    const row = (await screen.findByText("lewis-rag-2020.pdf")).closest("tr")!;
    expect(within(row).getByText("General")).toBeVisible();
    expect(within(row).queryByText("Not chosen yet")).toBeNull();
    expect(within(row).queryByText("You can choose subjects when processing finishes.")).toBeNull();
  });

  it("shows a failed document's reason", async () => {
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [duplicate]} upload={vi.fn()} />);
    const row = (await screen.findByText("copy.pdf")).closest("tr")!;
    expect(within(row).getByText("Failed")).toBeVisible();
    expect(within(row).getByText("This file isn't a readable PDF")).toBeVisible();
  });

  it("uploads the picked PDF and refreshes the list", async () => {
    let activeLoads = 0;
    const load = vi.fn(async (f: DocumentFilters) => (f.archived ? [] : (activeLoads++ === 0 ? [] : [processing])));
    const upload = vi.fn(async () => {});
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={upload} />);
    await screen.findByText("Upload your first document");
    const file = new File(["%PDF"], "lewis-rag-2020.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), file);
    expect(upload).toHaveBeenCalledWith(file, expect.any(Object));
    expect(screen.getByRole("status")).toHaveTextContent(/Uploading lewis-rag-2020.pdf…|Uploaded lewis-rag-2020.pdf. Processing./);
    expect(await screen.findByRole("cell", { name: /lewis-rag-2020\.pdf/ })).toBeVisible(); // the tray also lists the name
  });

  it("shows an error when the upload fails", async () => {
    const upload = vi.fn(async () => {
      throw new Error("Upload to storage failed (403)");
    });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "big.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("Couldn't upload big.pdf. Try again.")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Upload failed: big.pdf.");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("refuses a non-PDF and an oversized file in the browser, uploads the rest, and says why", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} load={async () => []} upload={upload} loadLimits={limits} />);
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
    expect(upload).toHaveBeenCalledWith(good, expect.any(Object));
  });

  it("announces every refusal reason and the upload in the one status region", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} load={async () => []} upload={upload} loadLimits={limits} />);
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
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} load={async () => []} upload={upload} loadLimits={async () => { throw new Error("down"); }} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "notes.docx", { type: "application/msword" }), { applyAccept: false });
    expect(await screen.findByText("Not uploaded. Only PDF files can be uploaded.")).toBeVisible();
    expect(screen.queryByText(/Couldn't upload/)).toBeNull();
    expect(upload).not.toHaveBeenCalled();
  });

  it("loads the limits once when the loader is an inline function", async () => {
    const loadLimits = vi.fn(limits);
    const { rerender } = render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} load={async () => []} upload={vi.fn()} loadLimits={() => loadLimits()} />);
    await screen.findByText(/PDFs up to 50 MB/);
    rerender(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} load={async () => []} upload={vi.fn()} loadLimits={() => loadLimits()} />);
    expect(loadLimits).toHaveBeenCalledTimes(1);
  });

  it("makes no request at all for a refused file", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const upload = vi.fn(async () => {});
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} load={async () => []} upload={upload} loadLimits={limits} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "a.txt", { type: "text/plain" }), { applyAccept: false });
    expect(await screen.findByText("Not uploaded. Only PDF files can be uploaded.")).toBeVisible();
    expect(upload).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    fetch.mockRestore();
  });

  it("states the limits from settings in the first-run card", async () => {
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} load={async () => []} upload={vi.fn()} loadLimits={async () => ({ max_bytes: 10 * 1_048_576, max_pages: 200 })} />);
    expect(await screen.findByText(/PDFs up to 10 MB and 200 pages/)).toBeVisible();
  });

  it("never uploads when the limits can't be loaded", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} load={async () => []} upload={upload} loadLimits={async () => { throw new Error("down"); }} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["%PDF"], "paper.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("Couldn't upload paper.pdf. Try again.")).toBeVisible();
    expect(upload).not.toHaveBeenCalled();
  });

  it("announces a processing state change in the status region, but not the first load", async () => {
    const failedNow: DocumentResponse = { ...processing, state: "failed", failure_reason: "This file isn't a readable PDF" };
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve)); // the change arrives only after the first-load check
    const load = vi
      .fn()
      .mockResolvedValueOnce([processing])
      .mockImplementation(async () => {
        await gate;
        return [failedNow];
      });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} pollMs={20} />);
    await screen.findByText("lewis-rag-2020.pdf"); // not "Processing": the State filter has that option too
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    release();
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("lewis-rag-2020.pdf failed: This file isn't a readable PDF."),
    );
  });

  it("refreshes every 2 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const load = vi.fn(async () => [processing]);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4100);
    });
    expect(load.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("skips the upload of a file already in the library and links to its row", async () => {
    const upload = vi.fn(async () => {});
    const check = vi.fn(async () => "d1");
    render(<LibraryPage loadSubjects={noSubjects} loadLimits={limits} load={async () => [processing]} upload={upload} check={check} />);
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
    render(<LibraryPage loadSubjects={noSubjects} loadLimits={limits} load={async () => [processing]} upload={upload} check={check} />);
    await screen.findByText("lewis-rag-2020.pdf");
    const have = new File(["%PDF a"], "have.pdf", { type: "application/pdf" });
    const fresh = new File(["%PDF b"], "fresh.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), [have, fresh]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(upload).toHaveBeenCalledWith(fresh, expect.any(Object));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("have.pdf: Already in your library. Uploaded fresh.pdf. Processing."),
    );
  });

  it("uploads anyway when the check fails", async () => {
    const upload = vi.fn(async () => {});
    const check = vi.fn(async () => {
      throw new Error("500");
    });
    render(<LibraryPage loadSubjects={noSubjects} loadLimits={limits} load={async () => []} upload={upload} check={check} />);
    await screen.findByText("Upload your first document");
    const file = new File(["%PDF"], "x.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), file);
    await waitFor(() => expect(upload).toHaveBeenCalledWith(file, expect.any(Object)));
  });

  it("does not check a rejected file", async () => {
    const check = vi.fn(async () => null);
    render(<LibraryPage loadSubjects={noSubjects} loadLimits={limits} load={async () => []} upload={vi.fn()} check={check} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "notes.docx", { type: "application/msword" }), { applyAccept: false });
    expect(check).not.toHaveBeenCalled();
  });
});

describe("LibraryPage drop zone and upload tray", () => {
  const pdf = (name: string) => new File(["%PDF"], name, { type: "application/pdf" });
  const drop = (files: File[]) => {
    fireEvent.dragEnter(document.body, { dataTransfer: { types: ["Files"], files: [] } });
    fireEvent.drop(document.body, { dataTransfer: { types: ["Files"], files } });
  };

  // An upload that waits until the test settles it, so the tray can be seen mid-flight.
  function controlledUpload() {
    const pending = new Map<string, { events: UploadEvents; resolve: () => void; reject: (e: Error) => void }>();
    const upload = vi.fn(
      (file: File, events: UploadEvents) =>
        new Promise<void>((resolve, reject) => {
          pending.set(file.name, { events, resolve, reject });
        }),
    );
    return { upload, pending };
  }

  it("highlights the page on drag-over and clears it on drag-leave", async () => {
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={vi.fn()} />);
    await screen.findByText("Upload your first document");
    fireEvent.dragEnter(document.body, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
    fireEvent.dragLeave(document.body, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
  });

  it("uploads three dropped PDFs in parallel, each with its own progress bar", async () => {
    const { upload, pending } = controlledUpload();
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")]);
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(3)); // all three started before any finished
    const tray = screen.getByRole("region", { name: "Uploading 3 files…" });
    act(() => pending.get("b.pdf")!.events.onProgress!(0.5));
    expect(within(tray).getByRole("progressbar", { name: "Upload progress for b.pdf" })).toHaveAttribute("aria-valuenow", "50");
    expect(within(tray).getAllByRole("progressbar")).toHaveLength(3);
    await act(async () => {
      for (const p of pending.values()) p.resolve();
    });
    expect(await screen.findByRole("region", { name: "Uploads · 3 files" })).toBeVisible();
    expect(within(screen.getByRole("region", { name: "Uploads · 3 files" })).getAllByText("Uploaded · processing")).toHaveLength(3);
    expect(screen.getByRole("status")).toHaveTextContent("Uploaded a.pdf. Processing. Uploaded b.pdf. Processing. Uploaded c.pdf. Processing.");
  });

  it("refuses a dropped non-PDF the same way as a picked one", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([new File(["x"], "reading-list.docx", { type: "application/msword" }), pdf("paper.pdf")]);
    const list = await screen.findByRole("list", { name: "Files not uploaded" });
    expect(within(list).getByText("Not uploaded. Only PDF files can be uploaded.")).toBeVisible();
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect((upload.mock.calls[0] as unknown as [File])[0].name).toBe("paper.pdf");
  });

  it("keeps the other uploads going when one fails", async () => {
    const { upload, pending } = controlledUpload();
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("a.pdf"), pdf("b.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    await act(async () => pending.get("a.pdf")!.reject(new Error("Upload to storage failed (403)")));
    const tray = screen.getByRole("region", { name: "Uploading 1 file…" });
    expect(within(tray).getByText("Upload failed")).toBeVisible();
    expect(within(tray).getByRole("progressbar", { name: "Upload progress for b.pdf" })).toBeVisible();
    await act(async () => pending.get("b.pdf")!.resolve());
    expect(await screen.findByText("Couldn't upload a.pdf. Try again.")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Upload failed: a.pdf. Uploaded b.pdf. Processing.");
  });

  it("adds a second drop to the same tray, newest first, and hides Close until all finish", async () => {
    const { upload, pending } = controlledUpload();
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("first.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    drop([pdf("second.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    const tray = screen.getByRole("region", { name: "Uploading 2 files…" });
    expect(within(tray).getAllByRole("listitem").map((li) => li.textContent)).toEqual([expect.stringContaining("second.pdf"), expect.stringContaining("first.pdf")]);
    await act(async () => pending.get("first.pdf")!.resolve());
    expect(within(tray).queryByRole("button", { name: "Close uploads" })).toBeNull();
    await act(async () => pending.get("second.pdf")!.resolve());
    await userEvent.click(await screen.findByRole("button", { name: "Close uploads" }));
    expect(screen.queryByRole("region", { name: /Uploads/ })).toBeNull();
  });

  it("announces both batches when a second drop starts before the first finishes", async () => {
    const { upload, pending } = controlledUpload();
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("a.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    drop([pdf("b.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    await act(async () => pending.get("a.pdf")!.reject(new Error("x")));
    await act(async () => pending.get("b.pdf")!.resolve());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Uploaded b.pdf. Processing."));
    expect(screen.getByRole("status")).toHaveTextContent("Upload failed: a.pdf.");
    expect(screen.getByText("Couldn't upload a.pdf. Try again.")).toBeVisible();

    // A fresh batch after everything settled starts the messages over.
    drop([pdf("c.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(3));
    expect(screen.getByRole("status")).not.toHaveTextContent("a.pdf");
    expect(screen.queryByText("Couldn't upload a.pdf. Try again.")).toBeNull();
    await act(async () => pending.get("c.pdf")!.resolve());
  });

  it("uploads at most three files at a time", async () => {
    const { upload, pending } = controlledUpload();
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop(["a", "b", "c", "d", "e"].map((n) => pdf(`${n}.pdf`)));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(3));
    await act(async () => {});
    expect(upload).toHaveBeenCalledTimes(3);
    const tray = screen.getByRole("region", { name: "Uploading 5 files…" });
    expect(within(tray).getAllByRole("listitem")).toHaveLength(5);
    await act(async () => pending.get("a.pdf")!.resolve());
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(4));
    await act(async () => {
      for (const p of pending.values()) p.resolve();
    });
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(5));
    await act(async () => {
      for (const p of pending.values()) p.resolve();
    });
    expect(await screen.findByRole("region", { name: "Uploads · 5 files" })).toBeVisible();
  });

  it("removes a queued file from the tray when it is already in the library", async () => {
    const { upload, pending } = controlledUpload();
    const check = vi.fn(async (f: File) => (f.name === "have.pdf" ? "d1" : null));
    render(<LibraryPage loadSubjects={noSubjects} check={check} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("have.pdf"), pdf("fresh.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    const list = await screen.findByRole("list", { name: "Already in your library" });
    expect(within(list).getByText("have.pdf")).toBeVisible();
    const tray = screen.getByRole("region", { name: "Uploading 1 file…" });
    expect(within(tray).queryByText("have.pdf")).toBeNull();
    expect(within(tray).getByText("fresh.pdf")).toBeVisible();
    await act(async () => pending.get("fresh.pdf")!.resolve());
  });

  it("shows the new row as Uploading until its file reaches storage, then Processing", async () => {
    const { upload, pending } = controlledUpload();
    const row: DocumentResponse = { ...processing, document_id: "d9", title: "a.pdf" };
    let activeLoads = 0;
    const load = vi.fn(async (f: DocumentFilters) => (f.archived ? [] : (activeLoads++ === 0 ? [] : [row])));
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("a.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    act(() => pending.get("a.pdf")!.events.onStarted!("d9", "u9"));
    const tr = (await screen.findByRole("cell", { name: /a\.pdf/ })).closest("tr")!;
    expect(within(tr).getByText("Uploading")).toBeVisible();
    expect(within(tr).queryByText("You can choose subjects when processing finishes.")).toBeNull();
    await act(async () => pending.get("a.pdf")!.resolve());
    expect(await within(tr).findByText("Processing")).toBeVisible();
  });

  it("turns the tray row into Already in your library when the server finds a duplicate", async () => {
    const upload = vi.fn(async (_file: File, events: UploadEvents) => events.onStarted?.("d9", "u9"));
    const loadUpload = vi
      .fn()
      .mockResolvedValueOnce({ upload_id: "u9", outcome: null, document_id: null, archived: false })
      .mockResolvedValue({ upload_id: "u9", outcome: "duplicate", document_id: "d1", archived: false });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={upload} loadUpload={loadUpload} pollMs={20} />);
    await screen.findByText("lewis-rag-2020.pdf");
    drop([pdf("copy.pdf")]);
    const tray = await screen.findByRole("region", { name: "Uploads · 1 file" });
    expect(await within(tray).findByText("Already in your library")).toBeVisible();
    expect(within(tray).getByRole("link", { name: "Open document" })).toHaveAttribute("href", "#document-d1");
    expect(loadUpload).toHaveBeenCalledWith("u9");
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("copy.pdf: Already in your library."));
  });

  const startsUpload = (uploadId: string) => vi.fn(async (_file: File, events: UploadEvents) => events.onStarted?.("d9", uploadId));
  const advance = (ms: number) =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  // Polls run only when a test advances the clock, so the tests stay fast and in order.
  const POLL = 1000;
  // Drops the file and waits until it is sent, when the page starts asking about the upload.
  async function dropSent(name: string) {
    await screen.findByText("lewis-rag-2020.pdf");
    drop([pdf(name)]);
    await within(await screen.findByRole("region", { name: "Uploads · 1 file" })).findByText("Uploaded · processing");
  }

  const page = (loadUpload: (uploadId: string) => Promise<UploadStatus>) => (
    <LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={startsUpload("u9")} loadUpload={loadUpload} pollMs={POLL} />
  );

  it("keeps a stored upload as Uploaded and stops asking", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const loadUpload = vi.fn(async () => ({ upload_id: "u9", outcome: "stored" as const, document_id: "d9", archived: false }));
    render(page(loadUpload));
    await dropSent("fresh.pdf");
    await advance(POLL);
    expect(loadUpload).toHaveBeenCalledTimes(1);
    await advance(5 * POLL);
    expect(loadUpload).toHaveBeenCalledTimes(1);
    expect(within(screen.getByRole("region", { name: "Uploads · 1 file" })).getByText("Uploaded · processing")).toBeVisible();
  });

  it("stops asking about the upload when the session expires", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const loadUpload = vi.fn(async (): Promise<UploadStatus> => {
      throw new SessionExpiredError();
    });
    render(page(loadUpload));
    await dropSent("fresh.pdf");
    await advance(POLL);
    expect(loadUpload).toHaveBeenCalledTimes(1);
    await advance(5 * POLL);
    expect(loadUpload).toHaveBeenCalledTimes(1);
  });

  it("asks again after a failed status check and still finds the duplicate", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const loadUpload = vi
      .fn()
      .mockRejectedValueOnce(new Error("500"))
      .mockResolvedValue({ upload_id: "u9", outcome: "duplicate", document_id: "d1", archived: false });
    render(page(loadUpload));
    await dropSent("copy.pdf");
    await advance(POLL);
    expect(loadUpload).toHaveBeenCalledTimes(1);
    await advance(POLL);
    const tray = screen.getByRole("region", { name: "Uploads · 1 file" });
    expect(await within(tray).findByText("Already in your library")).toBeVisible();
    expect(loadUpload).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status")).toHaveTextContent("copy.pdf: Already in your library.");
  });

  it("stops asking about the upload when the page closes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const loadUpload = vi.fn(async () => ({ upload_id: "u9", outcome: null, document_id: null, archived: false }));
    const { unmount } = render(page(loadUpload));
    await dropSent("fresh.pdf");
    await advance(POLL);
    expect(loadUpload).toHaveBeenCalledTimes(1);
    unmount();
    await advance(5 * POLL);
    expect(loadUpload).toHaveBeenCalledTimes(1);
  });

  it("says an archived duplicate is already in the library, archived, with no link", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const loadUpload = vi.fn(async () => ({ upload_id: "u9", outcome: "duplicate" as const, document_id: "d1", archived: true }));
    render(page(loadUpload));
    await dropSent("old.pdf");
    await advance(POLL);
    const tray = screen.getByRole("region", { name: "Uploads · 1 file" });
    expect(await within(tray).findByText("Already in your library, archived")).toBeVisible();
    expect(within(tray).queryByRole("link", { name: "Open document" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("old.pdf: Already in your library, archived.");
  });

  it("restores an archived duplicate from the tray, then links to it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const loadUpload = vi.fn(async () => ({ upload_id: "u9", outcome: "duplicate" as const, document_id: "d1", archived: true }));
    const restore = vi.fn(async () => processing);
    const load = vi.fn(async () => [processing]);
    const loadSubjects = vi.fn(noSubjects);
    render(<LibraryPage loadSubjects={loadSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={startsUpload("u9")} loadUpload={loadUpload} restore={restore} pollMs={POLL} />);
    await dropSent("old.pdf");
    await advance(POLL);
    const tray = screen.getByRole("region", { name: "Uploads · 1 file" });
    const loadsBefore = load.mock.calls.length;
    await userEvent.click(await within(tray).findByRole("button", { name: "Restore old.pdf" }));
    expect(restore).toHaveBeenCalledExactlyOnceWith("d1");
    expect(await within(tray).findByText("Already in your library")).toBeVisible();
    expect(within(tray).getByRole("link", { name: "Open document" })).toHaveAttribute("href", "#document-d1");
    expect(within(tray).queryByRole("button", { name: "Restore old.pdf" })).toBeNull();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("old.pdf restored."));
    expect(load.mock.calls.length).toBeGreaterThan(loadsBefore);
    expect(loadSubjects.mock.calls.length).toBeGreaterThan(1);
  });

  it("marks a duplicate without a document as already in the library, with no link", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const loadUpload = vi.fn(async () => ({ upload_id: "u9", outcome: "duplicate" as const, document_id: null, archived: false }));
    render(page(loadUpload));
    await dropSent("copy.pdf");
    await advance(POLL);
    const tray = screen.getByRole("region", { name: "Uploads · 1 file" });
    expect(await within(tray).findByText("Already in your library")).toBeVisible();
    expect(within(tray).queryByRole("link", { name: "Open document" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("copy.pdf: Already in your library.");
    await advance(5 * POLL);
    expect(loadUpload).toHaveBeenCalledTimes(1);
  });

  it("announces a late duplicate without overwriting a newer batch's message", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { upload, pending } = controlledUpload();
    let aIsDuplicate = false;
    const loadUpload = vi.fn(async (uploadId: string) =>
      uploadId === "ua" && aIsDuplicate
        ? { upload_id: uploadId, outcome: "duplicate" as const, document_id: "d1", archived: false }
        : { upload_id: uploadId, outcome: null, document_id: null, archived: false },
    );
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={upload} loadUpload={loadUpload} pollMs={POLL} />);
    await screen.findByText("lewis-rag-2020.pdf");
    const status = screen.getByRole("status");

    drop([pdf("a.pdf")]);
    await waitFor(() => expect(pending.has("a.pdf")).toBe(true));
    act(() => pending.get("a.pdf")!.events.onStarted!("da", "ua"));
    await act(async () => pending.get("a.pdf")!.resolve());
    await waitFor(() => expect(status).toHaveTextContent("Uploaded a.pdf. Processing."));

    // A new batch resets the live region; b1.pdf takes the slot a.pdf had.
    drop([pdf("b1.pdf"), pdf("b2.pdf")]);
    await waitFor(() => expect(pending.has("b2.pdf")).toBe(true));
    act(() => pending.get("b1.pdf")!.events.onStarted!("db1", "ub1"));
    await act(async () => pending.get("b1.pdf")!.resolve());
    await waitFor(() => expect(status).toHaveTextContent("Uploaded b1.pdf. Processing. Uploading b2.pdf…"));
    expect(status).not.toHaveTextContent("a.pdf");

    aIsDuplicate = true;
    await advance(POLL);
    await waitFor(() => expect(status).toHaveTextContent("a.pdf: Already in your library."));

    act(() => pending.get("b2.pdf")!.events.onStarted!("db2", "ub2"));
    await act(async () => pending.get("b2.pdf")!.resolve());
    await waitFor(() => expect(status).toHaveTextContent("Uploaded b1.pdf. Processing. Uploaded b2.pdf. Processing."));
  });

  it("uploads by keyboard from the Upload button", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={upload} />);
    const button = await screen.findByRole("button", { name: "Upload" });
    const input = screen.getByLabelText("Upload PDFs") as HTMLInputElement;
    const click = vi.spyOn(input, "click");
    button.focus();
    await userEvent.keyboard("{Enter}");
    expect(click).toHaveBeenCalled();
  });

  it("tells the learner they can drop files in the first-run card", async () => {
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={vi.fn()} />);
    expect(await screen.findByText("Or drop files anywhere on this page. You can add several at once.")).toBeVisible();
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
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [waiting, duplicate, processing]} upload={vi.fn()} />);
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
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} loadSuggestions={loadSuggestions} saveSubjects={saveSubjects} pollMs={60_000} />);
    await userEvent.click(await screen.findByRole("button", { name: "Choose subjects for Toolformer" }));
    expect(screen.getByRole("dialog", { name: "Choose subjects" })).toBeVisible();
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect(saveSubjects).toHaveBeenCalledWith("d1", { subject_ids: ["s1"], new_names: [] });
    await waitFor(() => expect(pageStatus()).toHaveTextContent("Subjects saved. Toolformer is ready to use."));
    await waitFor(() => expect(load).toHaveBeenCalledTimes(6)); // on mount the list and both tab counts, then the list and both tab counts again
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(pageStatus()).toHaveFocus();
    expect((await screen.findByText("Toolformer")).closest("tr")).toHaveTextContent("AI Agents");
  });

  it("ignores a file dropped while the picker is open", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [waiting]} upload={upload} loadSuggestions={async () => suggestions} />);
    await userEvent.click(await screen.findByRole("button", { name: "Choose subjects for Toolformer" }));
    expect(screen.getByRole("dialog", { name: "Choose subjects" })).toBeVisible();
    fireEvent.dragEnter(document.body, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
    fireEvent.drop(document.body, { dataTransfer: { types: ["Files"], files: [new File(["%PDF"], "x.pdf", { type: "application/pdf" })] } });
    await act(async () => {});
    expect(upload).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: /Upload/ })).toBeNull();
  });

  it("keeps 'Subjects saved.' when a stale poll lands between the save and the reload", async () => {
    const ready: DocumentResponse = { ...waiting, state: "ready", subjects: [{ subject_id: "s1", name: "AI Agents" }] };
    let afterSave = 0; // the first load after the save is a poll that started before it
    let didSave = false;
    const load = vi.fn(async () => (didSave && afterSave++ > 0 ? [ready] : [waiting]));
    const saveSubjects = async () => {
      didSave = true;
      return ready;
    };
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} loadSuggestions={async () => suggestions} saveSubjects={saveSubjects} pollMs={50} />);
    await userEvent.click(await screen.findByRole("button", { name: "Choose subjects for Toolformer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    await waitFor(() => expect(load.mock.calls.length).toBeGreaterThan(2));
    await waitFor(() => expect(afterSave).toBeGreaterThan(2));
    expect(pageStatus()).toHaveTextContent("Subjects saved. Toolformer is ready to use.");
    expect(pageStatus()).not.toHaveTextContent("Toolformer is ready.");
  });
});

const scan: DocumentResponse = { document_id: "d3", title: "scan.pdf", state: "failed", failure_reason: "No text layer (scanned PDFs are not supported yet)", created_at: today, subjects: [], attempt: 1, max_attempts: 3, can_retry: true, authors: [], year: null, archived: false };

describe("LibraryPage retry", () => {
  it("retries a failed document and refreshes the list", async () => {
    const load = vi.fn().mockResolvedValueOnce([scan]).mockResolvedValue([{ ...scan, state: "processing", failure_reason: null, attempt: 2, can_retry: false }]);
    const retry = vi.fn(async () => {});
    render(<LibraryPage loadSubjects={noSubjects} loadLimits={limits} load={load} upload={vi.fn()} retry={retry} />);
    const row = (await screen.findByText("scan.pdf")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Retry scan.pdf" }));
    expect(retry).toHaveBeenCalledWith("d3");
    expect(await within(row).findByText(/^Attempt 2 of 3 · /)).toBeVisible();
    expect(within(row).getByText("Processing")).toBeVisible();
    expect(within(row).queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("shows no Retry once the attempts are used up", async () => {
    const usedUp = { ...scan, failure_reason: "This file could not be processed", attempt: 3, can_retry: false };
    render(<LibraryPage loadSubjects={noSubjects} loadLimits={limits} load={async () => [usedUp]} upload={vi.fn()} retry={vi.fn()} />);
    const row = (await screen.findByText("scan.pdf")).closest("tr")!;
    expect(within(row).getByText("This file could not be processed")).toBeVisible();
    expect(within(row).queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("shows no Retry for a failed document without a retry", async () => {
    render(<LibraryPage loadSubjects={noSubjects} loadLimits={limits} load={async () => [duplicate]} upload={vi.fn()} retry={vi.fn()} />);
    const row = (await screen.findByText("copy.pdf")).closest("tr")!;
    expect(within(row).queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("says so when a retry fails", async () => {
    const retry = vi.fn(async () => {
      throw new Error("POST /documents/d3/retry failed (500)");
    });
    render(<LibraryPage loadSubjects={noSubjects} loadLimits={limits} load={async () => [scan]} upload={vi.fn()} retry={retry} />);
    const row = (await screen.findByText("scan.pdf")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Retry scan.pdf" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Couldn't retry scan.pdf. Try again.");
    expect(within(row).getByRole("button", { name: "Retry scan.pdf" })).toBeEnabled();
  });

  it("says the document could not be processed when the attempts are used up", async () => {
    const retry = vi.fn(async () => {
      throw new RetriesUsedUpError();
    });
    render(<LibraryPage loadSubjects={noSubjects} loadLimits={limits} load={async () => [scan]} upload={vi.fn()} retry={retry} />);
    const row = (await screen.findByText("scan.pdf")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Retry scan.pdf" }));
    expect(await screen.findByRole("status")).toHaveTextContent("scan.pdf could not be processed.");
  });

  describe("filters", () => {
    const ready: DocumentResponse = { ...processing, state: "ready", subjects: [{ subject_id: "s1", name: "AI Agents" }], authors: ["Timo Schick", "Jane Dwivedi-Yu", "Roberto Dessì"], year: 2023 };
    const subjects = async () => [
      { subject_id: "s1", name: "AI Agents" },
      { subject_id: "s2", name: "LLMs" },
    ];

    it("shows the byline and the filter bar with the count", async () => {
      render(<LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={subjects} load={async () => [ready]} upload={vi.fn()} />);
      expect(await screen.findByText("Schick et al. · 2023")).toBeVisible();
      expect(screen.getByRole("search", { name: "Filter documents" })).toBeVisible();
      expect(within(screen.getByRole("search", { name: "Filter documents" })).getByText("1 document")).toBeVisible();
      expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    });

    it("loads with the chosen subject, state and dates", async () => {
      const load = vi.fn(async () => [ready]);
      render(<LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={subjects} load={load} upload={vi.fn()} />);
      await screen.findByText("lewis-rag-2020.pdf");
      expect(load).toHaveBeenCalledWith({});
      await screen.findByRole("option", { name: "AI Agents" });
      await userEvent.selectOptions(screen.getByLabelText("Subject"), "s1");
      await waitFor(() => expect(load).toHaveBeenLastCalledWith({ subject_ids: ["s1"] }));
      await userEvent.selectOptions(screen.getByLabelText("State"), "awaiting_subjects");
      await waitFor(() => expect(load).toHaveBeenLastCalledWith({ subject_ids: ["s1"], state: "awaiting_subjects" }));
      await userEvent.click(screen.getByRole("button", { name: "Uploaded" }));
      fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } });
      fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-10-07" } });
      await waitFor(() => expect(load).toHaveBeenLastCalledWith({ subject_ids: ["s1"], state: "awaiting_subjects", uploaded_from: "2026-10-01", uploaded_to: "2026-10-07" }));
    });

    it("shows the no-results state, keeps Upload, and Clear filters restores the list and focuses Subject", async () => {
      const load = vi.fn(async (filters: { subject_ids?: string[] }) => (filters.subject_ids ? [] : [ready]));
      render(<LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={subjects} load={load} upload={vi.fn()} />);
      await screen.findByText("lewis-rag-2020.pdf");
      await screen.findByRole("option", { name: "LLMs" });
      await userEvent.selectOptions(screen.getByLabelText("Subject"), "s2");
      expect(await screen.findByText("No documents match these filters")).toBeVisible();
      expect(screen.getByText("Try another subject, state or a wider date range.")).toBeVisible();
      expect(screen.getByText("0 documents")).toBeVisible();
      expect(screen.queryByText("Upload your first document")).toBeNull();
      expect(screen.getByRole("button", { name: "Upload" })).toBeVisible();
      const clear = screen.getAllByRole("button", { name: "Clear filters" });
      await userEvent.click(clear[clear.length - 1]);
      expect(await screen.findByText("lewis-rag-2020.pdf")).toBeVisible();
      expect(load).toHaveBeenLastCalledWith({});
      expect(screen.getByLabelText("Subject")).toHaveValue("");
      expect(screen.getByLabelText("Subject")).toHaveFocus();
      expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    });

    it("keeps the upload empty state, without the filter bar, for an empty library with no filters", async () => {
      render(<LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={subjects} load={async () => []} upload={vi.fn()} />);
      expect(await screen.findByText("Upload your first document")).toBeVisible();
      expect(screen.queryByRole("search")).toBeNull();
      expect(screen.queryByText("No documents match these filters")).toBeNull();
    });

    it("does not announce documents entering or leaving the filtered set", async () => {
      const load = vi.fn(async (filters: { state?: string }) => (filters.state === "ready" ? [ready] : [{ ...processing, document_id: "d8", title: "pending.pdf" }, { ...ready, document_id: "d9", title: "other.pdf" }]));
      render(<LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={subjects} load={load} upload={vi.fn()} />);
      await screen.findByText("other.pdf");
      await userEvent.selectOptions(screen.getByLabelText("State"), "ready");
      await waitFor(() => expect(screen.queryByText("other.pdf")).toBeNull());
      expect(screen.getByRole("status")).toBeEmptyDOMElement();
    });

    it("still lists documents when the subjects fail to load", async () => {
      const broken = async () => {
        throw new Error("down");
      };
      render(<LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={broken} load={async () => [ready]} upload={vi.fn()} />);
      expect(await screen.findByText("lewis-rag-2020.pdf")).toBeVisible();
      expect([...(screen.getByLabelText("Subject") as HTMLSelectElement).options].map((o) => o.text)).toEqual(["All subjects"]);
    });
  });
});

describe("LibraryPage delete", () => {
  const cot: DocumentResponse = { ...processing, document_id: "d1", title: "Chain-of-Thought Prompting", state: "ready" };
  const other: DocumentResponse = { ...processing, document_id: "d2", title: "Attention", state: "ready" };
  const old: DocumentResponse = { ...processing, document_id: "d7", title: "GPT-3", state: "ready", archived: true };

  // A server in memory: delete removes the document from whichever list holds it.
  function library(active: DocumentResponse[], archived: DocumentResponse[] = []) {
    const lists = { active: [...active], archived: [...archived] };
    // Reloads after a delete take a moment, as over the network: the dialog has unmounted while the old row is still on screen.
    let deletedOne = false;
    const load = vi.fn(async (filters: DocumentFilters) => {
      if (deletedOne) await new Promise((resolve) => setTimeout(resolve, 20));
      return filters.archived ? lists.archived : lists.active;
    });
    const remove = vi.fn(async (id: string) => {
      deletedOne = true;
      lists.active = lists.active.filter((d) => d.document_id !== id);
      lists.archived = lists.archived.filter((d) => d.document_id !== id);
    });
    const archive = vi.fn(async (id: string) => ({ ...lists.active.find((d) => d.document_id === id)!, archived: true }));
    return { load, remove, archive };
  }

  const open = async (title: string) => {
    await userEvent.click(await screen.findByRole("button", { name: `More actions for ${title}` }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete…" }));
  };

  it("deletes after confirming, closes the dialog, refreshes, announces it, and focuses the Library heading", async () => {
    const { load, remove } = library([cot, other]);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} remove={remove} />);
    await open("Chain-of-Thought Prompting");
    expect(screen.getByRole("dialog", { name: "Delete Chain-of-Thought Prompting?" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(remove).toHaveBeenCalledExactlyOnceWith("d1");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(screen.queryByText("Chain-of-Thought Prompting")).toBeNull());
    expect(screen.getByRole("status")).toHaveTextContent("Chain-of-Thought Prompting deleted.");
    // The Dialog hands focus back to the button that opened it as it unmounts; the heading must win.
    expect(screen.getByRole("heading", { level: 1, name: "Library" })).toHaveFocus();
  });

  it("deletes an archived document from the Archived tab", async () => {
    const { load, remove } = library([cot], [old]);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} remove={remove} />);
    await userEvent.click(await screen.findByRole("tab", { name: /^Archived/ }));
    await open("GPT-3");
    expect(screen.queryByRole("button", { name: "Archive instead" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(remove).toHaveBeenCalledExactlyOnceWith("d7");
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("GPT-3 deleted."));
  });

  it("cancels without deleting and returns focus to the More button", async () => {
    const { load, remove } = library([cot]);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} remove={remove} />);
    await open("Chain-of-Thought Prompting");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(remove).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "More actions for Chain-of-Thought Prompting" })).toHaveFocus();
  });

  it("archives instead and closes the dialog", async () => {
    const { load, remove, archive } = library([cot, other]);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} remove={remove} archive={archive} />);
    await open("Chain-of-Thought Prompting");
    await userEvent.click(screen.getByRole("button", { name: "Archive instead" }));
    expect(archive).toHaveBeenCalledExactlyOnceWith("d1");
    expect(remove).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Chain-of-Thought Prompting archived. Find it under Archived."));
  });

  it("keeps the dialog open and shows the error inside it when the delete fails", async () => {
    const { load } = library([cot]);
    const remove = vi.fn(async () => {
      throw new Error("boom");
    });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} remove={remove} />);
    await open("Chain-of-Thought Prompting");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Couldn't delete Chain-of-Thought Prompting. Try again.");
    expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
  });

  it("treats a document that is already gone as deleted", async () => {
    const { load } = library([cot, other]);
    const remove = vi.fn(async () => {
      throw new DocumentGoneError();
    });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} remove={remove} />);
    await open("Chain-of-Thought Prompting");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("status")).toHaveTextContent("Chain-of-Thought Prompting deleted.");
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Library" })).toHaveFocus());
    expect(load.mock.calls.length).toBeGreaterThan(2);
  });

  it("closes the dialog and announces the server's message when the document is processing again", async () => {
    const { load } = library([cot]);
    const remove = vi.fn(async () => {
      throw new DocumentProcessingError("This document is still processing");
    });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} remove={remove} />);
    await open("Chain-of-Thought Prompting");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("status")).toHaveTextContent("Couldn't delete Chain-of-Thought Prompting: This document is still processing.");
  });

  it("starts the next delete dialog fresh after cancelling one whose request was in flight", async () => {
    const { load } = library([cot]);
    let fail: (error: Error) => void = () => {};
    const remove = vi.fn(() => new Promise<void>((_, reject) => (fail = reject)));
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} remove={remove} />);
    await open("Chain-of-Thought Prompting");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await open("Chain-of-Thought Prompting");
    expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
    fail(new Error("boom")); // the first request fails late
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
  });

  it("says nothing when the session expired during a delete", async () => {
    const { load } = library([cot]);
    const remove = vi.fn(async () => {
      throw new SessionExpiredError();
    });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} remove={remove} />);
    await open("Chain-of-Thought Prompting");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(remove).toHaveBeenCalled());
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });
});

describe("LibraryPage archive and restore", () => {
  const ready: DocumentResponse = { ...processing, document_id: "d1", title: "Toolformer", state: "ready" };
  const other: DocumentResponse = { ...processing, document_id: "d2", title: "Attention", state: "ready" };
  const old: DocumentResponse = { ...processing, document_id: "d7", title: "GPT-3", state: "awaiting_subjects", archived: true };

  // A server in memory: archive and restore move a document between the two lists.
  function library(active: DocumentResponse[], archived: DocumentResponse[]) {
    const lists = { active: [...active], archived: [...archived] };
    const load = vi.fn(async (filters: DocumentFilters) => (filters.archived ? lists.archived : lists.active));
    const move = (id: string, from: DocumentResponse[], toArchived: boolean) => {
      const doc = { ...from.find((d) => d.document_id === id)!, archived: toArchived };
      lists.active = toArchived ? lists.active.filter((d) => d.document_id !== id) : [doc, ...lists.active];
      lists.archived = toArchived ? [doc, ...lists.archived] : lists.archived.filter((d) => d.document_id !== id);
      return doc;
    };
    const archive = vi.fn(async (id: string) => move(id, lists.active, true));
    const restore = vi.fn(async (id: string) => move(id, lists.archived, false));
    return { load, archive, restore };
  }

  const tab = (name: "Active" | "Archived") => screen.getByRole("tab", { name: new RegExp(`^${name}`) });
  const NOTICE = "Archived documents aren't used for answers, but citations to them in past conversations still work. Restore a document to change its subjects.";

  it("shows Active and Archived tabs with unfiltered totals and the active total in the header", async () => {
    const { load } = library([ready, other], [old]);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} />);
    expect(await screen.findByText("2 active documents", { selector: "span:not([aria-live])" })).toBeVisible();
    expect(screen.getByRole("tablist", { name: "Library view" })).toBeVisible();
    expect(tab("Active")).toHaveAttribute("aria-selected", "true");
    expect(tab("Active")).toHaveTextContent("2");
    expect(tab("Archived")).toHaveTextContent("1");
    expect(load).toHaveBeenCalledWith({});
    expect(load).toHaveBeenCalledWith({ archived: true });
  });

  it("archives from the More menu, announces it, and moves the row to Archived", async () => {
    const { load, archive, restore } = library([ready, other], []);
    const loadSubjects = vi.fn(noSubjects);
    render(<LibraryPage loadSubjects={loadSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} archive={archive} restore={restore} />);
    await userEvent.click(await screen.findByRole("button", { name: "More actions for Toolformer" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    expect(archive).toHaveBeenCalledExactlyOnceWith("d1");
    const status = screen.getByRole("status");
    await waitFor(() => expect(status).toHaveTextContent("Toolformer archived. Find it under Archived."));
    await waitFor(() => expect(screen.queryByText("Toolformer")).toBeNull());
    await waitFor(() => expect(tab("Archived")).toHaveTextContent("1"));
    expect(tab("Active")).toHaveTextContent("1");
    expect(status).toHaveFocus();
    expect(loadSubjects.mock.calls.length).toBeGreaterThan(1);
  });

  it("does not announce a document that left the list because it was archived", async () => {
    const { load, archive } = library([ready, other], []);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} archive={archive} pollMs={20} />);
    await userEvent.click(await screen.findByRole("button", { name: "More actions for Toolformer" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    const callsAfter = load.mock.calls.length;
    await waitFor(() => expect(load.mock.calls.length).toBeGreaterThan(callsAfter + 2));
    expect(screen.getByRole("status")).toHaveTextContent(/^Toolformer archived\. Find it under Archived\.$/);
  });

  it("announces a failed archive and keeps the row", async () => {
    const { load } = library([ready], []);
    const archive = vi.fn(async () => {
      throw new Error("POST /documents/d1/archive failed (500)");
    });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} archive={archive} />);
    await userEvent.click(await screen.findByRole("button", { name: "More actions for Toolformer" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Couldn't archive Toolformer. Try again."));
    expect(screen.getByText("Toolformer")).toBeVisible();
    expect(screen.getByRole("button", { name: "More actions for Toolformer" })).toBeEnabled();
  });

  it("says nothing when the session expired during an archive", async () => {
    const { load } = library([ready], []);
    const archive = vi.fn(async () => {
      throw new SessionExpiredError();
    });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} archive={archive} />);
    await userEvent.click(await screen.findByRole("button", { name: "More actions for Toolformer" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    await waitFor(() => expect(archive).toHaveBeenCalled());
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("shows the Archived tab: the notice, the Archived badge, Restore, and no Choose subjects or State filter", async () => {
    const { load } = library([ready], [old]);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} />);
    await screen.findByText("Toolformer");
    expect(screen.getByLabelText("State")).toBeVisible();
    await userEvent.click(tab("Archived"));
    const row = (await screen.findByText("GPT-3")).closest("tr")!;
    expect(load).toHaveBeenLastCalledWith({ archived: true });
    expect(tab("Archived")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(NOTICE)).toBeVisible();
    expect(within(row).getByText("Archived")).toBeVisible();
    expect(within(row).getByRole("button", { name: "Restore GPT-3" })).toBeEnabled();
    expect(within(row).queryByRole("button", { name: /Choose subjects/ })).toBeNull();
    expect(within(row).getByRole("button", { name: "More actions for GPT-3" })).toBeEnabled();
    expect(screen.queryByLabelText("State")).toBeNull();
    expect(screen.queryByRole("button", { name: /needs? subjects/ })).toBeNull();
  });

  it("keeps the subject and date filters across tabs and drops the state", async () => {
    const { load } = library([ready], [old]);
    const subjects = async () => [{ subject_id: "s1", name: "AI Agents" }];
    render(<LibraryPage loadSubjects={subjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} />);
    await screen.findByRole("option", { name: "AI Agents" });
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "s1");
    await userEvent.selectOptions(screen.getByLabelText("State"), "ready");
    await waitFor(() => expect(load).toHaveBeenLastCalledWith({ subject_ids: ["s1"], state: "ready" }));
    await userEvent.click(tab("Archived"));
    await waitFor(() => expect(load).toHaveBeenCalledWith({ subject_ids: ["s1"], archived: true }));
  });

  it("restores from the Archived tab, announces it, and the Active count goes up", async () => {
    const { load, archive, restore } = library([ready], [old]);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} archive={archive} restore={restore} />);
    await screen.findByText("Toolformer");
    await userEvent.click(tab("Archived"));
    await userEvent.click(await screen.findByRole("button", { name: "Restore GPT-3" }));
    expect(restore).toHaveBeenCalledExactlyOnceWith("d7");
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("GPT-3 restored."));
    await waitFor(() => expect(tab("Active")).toHaveTextContent("2"));
    expect(tab("Archived")).toHaveTextContent("0");
    expect(screen.queryByText("GPT-3")).toBeNull();
  });

  it("announces a failed restore", async () => {
    const { load } = library([], [old]);
    const restore = vi.fn(async () => {
      throw new Error("500");
    });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} restore={restore} />);
    await userEvent.click(await screen.findByRole("tab", { name: /^Archived/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Restore GPT-3" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Couldn't restore GPT-3. Try again."));
  });

  it("shows the empty Archived tab", async () => {
    const { load } = library([ready], []);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} />);
    await screen.findByText("Toolformer");
    await userEvent.click(tab("Archived"));
    expect(await screen.findByText("No archived documents")).toBeVisible();
    expect(screen.getByText("Archived documents leave search until you restore them.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Choose PDFs" })).toBeNull();
    expect(screen.queryByText("Upload your first document")).toBeNull();
  });

  it("keeps the tabs reachable when every document is archived", async () => {
    const { load } = library([], [old]);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} />);
    expect(await screen.findByText("No active documents")).toBeVisible();
    expect(screen.getByText("Your documents are all archived. Restore one from Archived, or upload a new one.")).toBeVisible();
    expect(screen.queryByText("Upload your first document")).toBeNull();
    expect(screen.getAllByRole("button", { name: "Upload" })).toHaveLength(2);
    expect(screen.getByText("Only upload documents you have the right to use.")).toBeVisible();
    await waitFor(() => expect(tab("Archived")).toHaveTextContent("1"));
  });

  it("offers no State in the empty filtered sentence on the Archived tab", async () => {
    const { load } = library([ready], [old]);
    const subjects = async () => [{ subject_id: "s1", name: "AI Agents" }];
    const filteredLoad = vi.fn(async (f: DocumentFilters) => (f.subject_ids?.length ? [] : load(f)));
    render(<LibraryPage loadSubjects={subjects} check={notInLibrary} loadLimits={limits} load={filteredLoad} upload={vi.fn()} />);
    await screen.findByRole("option", { name: "AI Agents" });
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "s1");
    expect(await screen.findByText("Try another subject, state or a wider date range.")).toBeVisible();
    await userEvent.click(tab("Archived"));
    expect(await screen.findByText("Try another subject or a wider date range.")).toBeVisible();
  });

  it("does not announce processing changes of an archived document", async () => {
    let state: DocumentResponse["state"] = "processing";
    const load = vi.fn(async (f: DocumentFilters) => (f.archived ? [{ ...old, state }] : [ready]));
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} pollMs={20} />);
    await screen.findByText("Toolformer");
    await userEvent.click(tab("Archived"));
    await screen.findByText("GPT-3");
    state = "awaiting_subjects";
    const calls = load.mock.calls.length;
    await waitFor(() => expect(load.mock.calls.length).toBeGreaterThan(calls + 3));
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });
});

describe("LibraryPage Chat on a row", () => {
  it("opens a new conversation that starts from the document", async () => {
    const ready: DocumentResponse = { ...processing, document_id: "d1", title: "Toolformer", state: "ready" };
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [ready]} upload={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Chat about Toolformer" }));
    expect(await screen.findByText("/chat?document=d1")).toBeVisible();
  });
});

describe("LibraryPage document details", () => {
  const row: DocumentResponse = { ...processing, document_id: "d1", title: "Toolformer", state: "ready" };
  const full = (title: string) => ({
    document_id: "d1", state: "ready" as const, archived: false, title, extracted_title: "Toolformer", title_overridden: title !== "Toolformer",
    authors: [], year: null, doi: null, file_name: "toolformer.pdf", pages: 10, summary: null, failure_reason: null, created_at: today,
    subjects: [], attempt: null, max_attempts: 3, can_retry: false,
  });

  function setup() {
    let title = "Toolformer";
    const load = vi.fn(async (f: DocumentFilters) => (f.archived ? [] : [{ ...row, title }]));
    const loadDetails = vi.fn(async (_id: string) => full(title));
    const saveTitle = vi.fn(async (_id: string, next: string | null) => {
      title = next ?? "Toolformer";
      return full(title);
    });
    const archive = vi.fn(async (_id: string) => ({ ...row, archived: true }));
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} loadDetails={loadDetails} saveTitle={saveTitle} archive={archive} />);
    return { load, loadDetails, saveTitle, archive };
  }

  it("opens a dialog from the row title and returns focus to it on close", async () => {
    setup();
    const opener = await screen.findByRole("button", { name: "Toolformer" });
    await userEvent.click(opener);
    expect(await screen.findByRole("dialog", { name: "Toolformer" })).toBeVisible();
    expect(screen.getByText("Document details")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Close document details" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("returns focus to the More button when the panel opened from the More menu closes", async () => {
    setup();
    await userEvent.click(await screen.findByRole("button", { name: "More actions for Toolformer" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Details" }));
    await userEvent.click(await screen.findByRole("button", { name: "Close document details" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "More actions for Toolformer" })).toHaveFocus(); // RowMenu keeps the toggle as the opener once its item is gone
  });

  it("opens Edit title from the More menu with the field focused", async () => {
    setup();
    await userEvent.click(await screen.findByRole("button", { name: "More actions for Toolformer" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Edit title" }));
    expect(await screen.findByRole("textbox", { name: "Display title" })).toHaveFocus();
  });

  it("re-lists after a title change", async () => {
    const { load } = setup();
    await userEvent.click(await screen.findByRole("button", { name: "Toolformer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Edit title" }));
    const field = screen.getByRole("textbox", { name: "Display title" });
    await userEvent.clear(field);
    await userEvent.type(field, "Tool use");
    const before = load.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Save title" }));
    await waitFor(() => expect(load.mock.calls.length).toBeGreaterThan(before));
    await userEvent.click(await screen.findByRole("button", { name: "Close document details" }));
    expect(await screen.findByRole("button", { name: "Tool use" })).toBeVisible();
  });

  it("re-lists after archiving from the panel", async () => {
    const { load, archive } = setup();
    await userEvent.click(await screen.findByRole("button", { name: "Toolformer" }));
    const before = load.mock.calls.length;
    await userEvent.click(await screen.findByRole("button", { name: "Archive" }));
    expect(archive).toHaveBeenCalledWith("d1");
    await waitFor(() => expect(load.mock.calls.length).toBeGreaterThan(before));
  });
});

describe("needs subjects", () => {
  const waiting = (id: string): DocumentResponse => ({ ...processing, document_id: id, title: `${id}.pdf`, state: "awaiting_subjects" });
  const ready: DocumentResponse = { ...processing, document_id: "r1", title: "r1.pdf", state: "ready", subjects: [{ subject_id: "s1", name: "AI Agents" }] };
  const subjects = async () => [{ subject_id: "s1", name: "AI Agents" }];

  it("counts waiting documents across the whole active library, not the filtered list", async () => {
    const load = vi.fn(async (f: DocumentFilters) => (f.subject_ids ? [ready] : [waiting("w1"), waiting("w2"), ready]));
    render(<LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={subjects} load={load} upload={vi.fn()} />);
    await screen.findByRole("option", { name: "AI Agents" });
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "s1");
    await waitFor(() => expect(load).toHaveBeenLastCalledWith({ subject_ids: ["s1"] }));
    expect(await screen.findByRole("button", { name: "2 need subjects" })).toBeVisible();
  });

  it("hides the chip when nothing waits", async () => {
    render(<LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={subjects} load={async () => [ready]} upload={vi.fn()} />);
    await screen.findByText("r1.pdf");
    expect(screen.queryByRole("button", { name: /need(s)? subjects/ })).toBeNull();
  });

  it("recounts when polling sees a state change", async () => {
    let state: DocumentResponse["state"] = "processing";
    const load = vi.fn(async () => [{ ...processing, state }]);
    render(<LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={subjects} load={load} upload={vi.fn()} pollMs={20} />);
    await screen.findByText("lewis-rag-2020.pdf");
    expect(screen.queryByRole("button", { name: /need(s)? subjects/ })).toBeNull();
    state = "awaiting_subjects";
    expect(await screen.findByRole("button", { name: "1 needs subjects" }, { timeout: 3000 })).toBeVisible();
  });

  describe("step-through", () => {
    const suggestion = { document_id: "x", title: "x", summary: null, suggestions: [{ subject_id: "s1", name: "AI Agents", origin: "yours" as const }] };
    const dialog = () => screen.getByRole("dialog", { name: "Choose subjects" });
    const pageStatus = () => screen.getAllByRole("status").find((el) => el.tagName === "P")!;

    function fixture(ids: string[]) {
      const docs = ids.map(waiting);
      const load = vi.fn(async (f: DocumentFilters) => (f.archived ? [] : docs.map((d) => ({ ...d }))));
      const saveSubjects = vi.fn(async (id: string) => {
        const doc = docs.find((d) => d.document_id === id)!;
        doc.state = "ready";
        doc.subjects = [{ subject_id: "s1", name: "AI Agents" }];
        return { ...doc };
      });
      const props = { loadSubjects: subjects, check: notInLibrary, loadLimits: limits, load, upload: vi.fn(), loadSuggestions: async () => suggestion, saveSubjects, pollMs: 60_000 };
      return { docs, load, saveSubjects, props };
    }

    it("steps through every waiting document, starting with the clicked one", async () => {
      const { saveSubjects, props } = fixture(["a", "b", "c"]);
      render(<LibraryPage {...props} />);
      await userEvent.click(await screen.findByRole("button", { name: "Choose subjects for b.pdf" }));
      expect(within(dialog()).getByText("Document 1 of 3")).toBeVisible();
      expect(within(dialog()).getByText("b.pdf")).toBeVisible();
      await userEvent.click(await screen.findByRole("button", { name: "Save and next" }));
      await waitFor(() => expect(within(dialog()).getByText("Document 2 of 3")).toBeVisible());
      expect(within(dialog()).getByText("a.pdf")).toBeVisible();
      await userEvent.click(screen.getByRole("button", { name: "Skip" }));
      await waitFor(() => expect(within(dialog()).getByText("Document 3 of 3")).toBeVisible());
      expect(within(dialog()).getByText("c.pdf")).toBeVisible();
      await userEvent.click(await screen.findByRole("button", { name: "Save" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(saveSubjects.mock.calls.map((c) => c[0])).toEqual(["b", "c"]);
      expect(pageStatus()).toHaveTextContent("Subjects saved for 2 documents. They're ready to use.");
    });

    it("queues waiting documents hidden by a filter", async () => {
      const { docs, props } = fixture(["a", "b", "c"]);
      const load = vi.fn(async (f: DocumentFilters) => (f.archived ? [] : f.subject_ids ? [{ ...docs[0]!, subjects: [{ subject_id: "s1", name: "AI Agents" }] }] : docs.map((d) => ({ ...d }))));
      render(<LibraryPage {...props} load={load} />);
      await screen.findByRole("option", { name: "AI Agents" });
      await userEvent.selectOptions(screen.getByLabelText("Subject"), "s1");
      await waitFor(() => expect(load).toHaveBeenLastCalledWith({ subject_ids: ["s1"] }));
      await userEvent.click(await screen.findByRole("button", { name: "Choose subjects for a.pdf" }));
      expect(within(dialog()).getByText("Document 1 of 3")).toBeVisible();
    });

    it("Skip on the last step closes quietly when nothing was saved", async () => {
      const { props } = fixture(["a", "b"]);
      render(<LibraryPage {...props} />);
      await userEvent.click(await screen.findByRole("button", { name: "Choose subjects for a.pdf" }));
      await userEvent.click(await screen.findByRole("button", { name: "Skip" }));
      await waitFor(() => expect(within(dialog()).getByText("Document 2 of 2")).toBeVisible());
      await userEvent.click(screen.getByRole("button", { name: "Skip" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(pageStatus()).not.toHaveTextContent(/saved/);
    });

    it("a single waiting document keeps the plain picker", async () => {
      const { saveSubjects, props } = fixture(["a"]);
      render(<LibraryPage {...props} />);
      await userEvent.click(await screen.findByRole("button", { name: "Choose subjects for a.pdf" }));
      expect(within(dialog()).getByText("Processing finished")).toBeVisible();
      expect(screen.getByRole("button", { name: "Cancel" })).toBeVisible();
      await userEvent.click(await screen.findByRole("button", { name: "Save" }));
      expect(await screen.findByText("Subjects saved.")).toBeVisible();
      expect(screen.getByRole("button", { name: "Done" })).toBeVisible();
      expect(saveSubjects).toHaveBeenCalledTimes(1);
    });
  });

  it("reports the count to the shell", async () => {
    const report = vi.fn();
    render(
      <NeedsSubjectsContext.Provider value={{ count: null, report }}>
        <LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={subjects} load={async () => [waiting("w1"), waiting("w2")]} upload={vi.fn()} />
      </NeedsSubjectsContext.Provider>,
    );
    await waitFor(() => expect(report).toHaveBeenCalledWith(2));
  });
});
