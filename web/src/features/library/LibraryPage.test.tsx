import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RetriesUsedUpError, type DocumentResponse, type UploadEvents } from "../../api/documents";
import { LibraryPage } from "./LibraryPage";

const today = new Date().toISOString();
const processing: DocumentResponse = { document_id: "d1", title: "lewis-rag-2020.pdf", state: "processing", failure_reason: null, created_at: today, subjects: [], attempt: null, max_attempts: 3, can_retry: false, authors: [], year: null };
const duplicate: DocumentResponse = { document_id: "d2", title: "copy.pdf", state: "failed", failure_reason: "Duplicate uploads aren't supported yet", created_at: today, subjects: [], attempt: null, max_attempts: 3, can_retry: false, authors: [], year: null };

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
    expect(upload).toHaveBeenCalledWith(file, expect.any(Object));
    expect(screen.getByRole("status")).toHaveTextContent(/Uploading lewis-rag-2020.pdf…|Uploaded lewis-rag-2020.pdf. Processing./);
    expect(await screen.findByRole("cell", { name: /lewis-rag-2020\.pdf/ })).toBeVisible(); // the tray also lists the name
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
    expect(upload).toHaveBeenCalledWith(good, expect.any(Object));
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
    render(<LibraryPage loadLimits={limits} load={async () => []} upload={upload} check={check} />);
    await screen.findByText("Upload your first document");
    const file = new File(["%PDF"], "x.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), file);
    await waitFor(() => expect(upload).toHaveBeenCalledWith(file, expect.any(Object)));
  });

  it("does not check a rejected file", async () => {
    const check = vi.fn(async () => null);
    render(<LibraryPage loadLimits={limits} load={async () => []} upload={vi.fn()} check={check} />);
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
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={vi.fn()} />);
    await screen.findByText("Upload your first document");
    fireEvent.dragEnter(document.body, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
    fireEvent.dragLeave(document.body, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
  });

  it("uploads three dropped PDFs in parallel, each with its own progress bar", async () => {
    const { upload, pending } = controlledUpload();
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
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
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([new File(["x"], "reading-list.docx", { type: "application/msword" }), pdf("paper.pdf")]);
    const list = await screen.findByRole("list", { name: "Files not uploaded" });
    expect(within(list).getByText("Not uploaded. Only PDF files can be uploaded.")).toBeVisible();
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect((upload.mock.calls[0] as unknown as [File])[0].name).toBe("paper.pdf");
  });

  it("keeps the other uploads going when one fails", async () => {
    const { upload, pending } = controlledUpload();
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
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
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
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
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
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
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
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
    render(<LibraryPage check={check} loadLimits={limits} load={async () => []} upload={upload} />);
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
    const load = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([row]);
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={load} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("a.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    act(() => pending.get("a.pdf")!.events.onStarted!("d9"));
    const tr = (await screen.findByRole("cell", { name: /a\.pdf/ })).closest("tr")!;
    expect(within(tr).getByText("Uploading")).toBeVisible();
    expect(within(tr).queryByText("You can choose subjects when processing finishes.")).toBeNull();
    await act(async () => pending.get("a.pdf")!.resolve());
    expect(await within(tr).findByText("Processing")).toBeVisible();
  });

  it("uploads by keyboard from the Upload button", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={upload} />);
    const button = await screen.findByRole("button", { name: "Upload" });
    const input = screen.getByLabelText("Upload PDFs") as HTMLInputElement;
    const click = vi.spyOn(input, "click");
    button.focus();
    await userEvent.keyboard("{Enter}");
    expect(click).toHaveBeenCalled();
  });

  it("tells the learner they can drop files in the first-run card", async () => {
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={vi.fn()} />);
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

  it("ignores a file dropped while the picker is open", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => [waiting]} upload={upload} loadSuggestions={async () => suggestions} />);
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
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={load} upload={vi.fn()} loadSuggestions={async () => suggestions} saveSubjects={saveSubjects} pollMs={50} />);
    await userEvent.click(await screen.findByRole("button", { name: "Choose subjects for Toolformer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    await waitFor(() => expect(load.mock.calls.length).toBeGreaterThan(2));
    await waitFor(() => expect(afterSave).toBeGreaterThan(2));
    expect(pageStatus()).toHaveTextContent("Subjects saved. Toolformer is ready to use.");
    expect(pageStatus()).not.toHaveTextContent("Toolformer is ready.");
  });
});

const scan: DocumentResponse = { document_id: "d3", title: "scan.pdf", state: "failed", failure_reason: "No text layer (scanned PDFs are not supported yet)", created_at: today, subjects: [], attempt: 1, max_attempts: 3, can_retry: true, authors: [], year: null };

describe("LibraryPage retry", () => {
  it("retries a failed document and refreshes the list", async () => {
    const load = vi.fn().mockResolvedValueOnce([scan]).mockResolvedValue([{ ...scan, state: "processing", failure_reason: null, attempt: 2, can_retry: false }]);
    const retry = vi.fn(async () => {});
    render(<LibraryPage loadLimits={limits} load={load} upload={vi.fn()} retry={retry} />);
    const row = (await screen.findByText("scan.pdf")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Retry scan.pdf" }));
    expect(retry).toHaveBeenCalledWith("d3");
    expect(await within(row).findByText("Attempt 2 of 3.")).toBeVisible();
    expect(within(row).getByText("Processing")).toBeVisible();
    expect(within(row).queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("shows no Retry once the attempts are used up", async () => {
    const usedUp = { ...scan, failure_reason: "This file could not be processed", attempt: 3, can_retry: false };
    render(<LibraryPage loadLimits={limits} load={async () => [usedUp]} upload={vi.fn()} retry={vi.fn()} />);
    const row = (await screen.findByText("scan.pdf")).closest("tr")!;
    expect(within(row).getByText("This file could not be processed")).toBeVisible();
    expect(within(row).queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("shows no Retry for a failed document without a retry", async () => {
    render(<LibraryPage loadLimits={limits} load={async () => [duplicate]} upload={vi.fn()} retry={vi.fn()} />);
    const row = (await screen.findByText("copy.pdf")).closest("tr")!;
    expect(within(row).queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("says so when a retry fails", async () => {
    const retry = vi.fn(async () => {
      throw new Error("POST /documents/d3/retry failed (500)");
    });
    render(<LibraryPage loadLimits={limits} load={async () => [scan]} upload={vi.fn()} retry={retry} />);
    const row = (await screen.findByText("scan.pdf")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Retry scan.pdf" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Couldn't retry scan.pdf. Try again.");
    expect(within(row).getByRole("button", { name: "Retry scan.pdf" })).toBeEnabled();
  });

  it("says the document could not be processed when the attempts are used up", async () => {
    const retry = vi.fn(async () => {
      throw new RetriesUsedUpError();
    });
    render(<LibraryPage loadLimits={limits} load={async () => [scan]} upload={vi.fn()} retry={retry} />);
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
      expect(screen.getByText("1 document")).toBeVisible();
      expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    });

    it("loads with the chosen subject, state and dates", async () => {
      const load = vi.fn(async () => [ready]);
      render(<LibraryPage check={notInLibrary} loadLimits={limits} loadSubjects={subjects} load={load} upload={vi.fn()} />);
      await screen.findByText("lewis-rag-2020.pdf");
      expect(load).toHaveBeenLastCalledWith({});
      await screen.findByRole("option", { name: "AI Agents" });
      await userEvent.selectOptions(screen.getByLabelText("Subject"), "s1");
      await waitFor(() => expect(load).toHaveBeenLastCalledWith({ subject_ids: ["s1"] }));
      await userEvent.selectOptions(screen.getByLabelText("State"), "awaiting_subjects");
      await waitFor(() => expect(load).toHaveBeenLastCalledWith({ subject_ids: ["s1"], state: "awaiting_subjects" }));
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
