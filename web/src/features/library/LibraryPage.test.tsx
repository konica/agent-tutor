import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RetriesUsedUpError, type DocumentResponse } from "../../api/documents";
import { LibraryPage } from "./LibraryPage";

const today = new Date().toISOString();
const processing: DocumentResponse = { document_id: "d1", title: "lewis-rag-2020.pdf", state: "processing", failure_reason: null, created_at: today, subjects: [], attempt: null, max_attempts: 3, can_retry: false };
const duplicate: DocumentResponse = { document_id: "d2", title: "copy.pdf", state: "failed", failure_reason: "Duplicate uploads aren't supported yet", created_at: today, subjects: [], attempt: null, max_attempts: 3, can_retry: false };

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

const scan: DocumentResponse = { document_id: "d3", title: "scan.pdf", state: "failed", failure_reason: "No text layer (scanned PDFs are not supported yet)", created_at: today, subjects: [], attempt: 1, max_attempts: 3, can_retry: true };

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
});
