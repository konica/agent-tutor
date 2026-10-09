import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { DocumentNotOpenableError, type DocumentResponse } from "../../api/documents";
import { DocumentViewer } from "./DocumentViewer";
import type { PdfDoc } from "./pdf";
import { fakeDocument, fakeFile, fakePdf } from "./testFakes";

const doc = fakeDocument;
const file = fakeFile;
const pdf = fakePdf;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

type Props = ComponentProps<typeof DocumentViewer>;

function renderViewer(props: Partial<Props> = {}) {
  const onClose = vi.fn();
  const loadFile = vi.fn().mockResolvedValue(file());
  const loadPdfDoc = vi.fn().mockResolvedValue(pdf());
  const restore = vi.fn();
  const all: Props = { documentId: "d1", mode: "pane", onClose, loadFile, loadPdfDoc, restore, ...props };
  const view = render(<DocumentViewer {...all} />);
  return { ...view, ...all, props: all };
}

const ready = () => screen.findByText("p. 1 / 3");

describe("DocumentViewer", () => {
  it("shows a skeleton, then the title and the page count", async () => {
    renderViewer();
    expect(screen.getByText("Loading document")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Document" })).toBeInTheDocument();
    await ready();
    expect(screen.getByRole("heading", { level: 2, name: "ReAct" })).toBeInTheDocument();
    expect(screen.queryByText("Loading document")).not.toBeInTheDocument();
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
  });

  it("pages with the buttons and PageDown/PageUp, and announces the page", async () => {
    const onPageChange = vi.fn();
    renderViewer({ onPageChange });
    await ready();
    const previous = screen.getByRole("button", { name: "Previous page" });
    expect(previous).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    expect(onPageChange).toHaveBeenLastCalledWith(2);
    await userEvent.click(previous);
    expect(screen.getByText("p. 1 / 3")).toBeInTheDocument();
    const title = screen.getByRole("heading", { level: 2 });
    fireEvent.keyDown(title, { key: "PageDown" });
    fireEvent.keyDown(title, { key: "PageDown" });
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    fireEvent.keyDown(title, { key: "PageDown" });
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    fireEvent.keyDown(title, { key: "PageUp" });
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
  });

  it("zooms in steps, clamped at 50% and 200%", async () => {
    renderViewer();
    await ready();
    expect(screen.getByText("100%")).toBeInTheDocument();
    const zoomIn = screen.getByRole("button", { name: "Zoom in" });
    const zoomOut = screen.getByRole("button", { name: "Zoom out" });
    await userEvent.click(zoomIn);
    expect(screen.getByText("125%")).toBeInTheDocument();
    await userEvent.click(zoomIn);
    await userEvent.click(zoomIn);
    await userEvent.click(zoomIn);
    expect(screen.getByText("200%")).toBeInTheDocument();
    expect(zoomIn).toBeDisabled();
    for (let i = 0; i < 5; i++) await userEvent.click(zoomOut);
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(zoomOut).toBeDisabled();
  });

  it("shows an error card when loading fails; Retry fetches a new link and shows the page", async () => {
    const loadFile = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(file());
    renderViewer({ loadFile });
    expect(await screen.findByText("We couldn't open this document.")).toBeInTheDocument();
    expect(screen.getByText("Check your connection and try again.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await ready();
    expect(loadFile).toHaveBeenCalledTimes(2);
  });

  it("shows the error card when the PDF fails to load, and Retry reloads it", async () => {
    const loadPdfDoc = vi.fn().mockRejectedValueOnce(new Error("bad pdf")).mockResolvedValue(pdf());
    const { loadFile } = renderViewer({ loadPdfDoc });
    expect(await screen.findByText("We couldn't open this document.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "ReAct" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await ready();
    expect(loadFile).toHaveBeenCalledTimes(2);
    expect(loadPdfDoc).toHaveBeenCalledTimes(2);
  });

  it("says a document still processing can't be opened, without Retry", async () => {
    renderViewer({ loadFile: vi.fn().mockRejectedValue(new DocumentNotOpenableError("processing")) });
    expect(await screen.findByText("This document can't be opened until it has been processed.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("restores an archived document and stays open", async () => {
    const restore = vi.fn().mockResolvedValue(doc());
    renderViewer({ loadFile: vi.fn().mockResolvedValue(file({ archived: true })), restore });
    await ready();
    expect(screen.getByText("Archived · read-only")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(restore).toHaveBeenCalledWith("d1");
    await waitFor(() => expect(screen.queryByText("Archived · read-only")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Restore" })).not.toBeInTheDocument();
    expect(screen.getByText("p. 1 / 3")).toBeInTheDocument();
  });

  it("says when restoring failed", async () => {
    const restore = vi.fn().mockRejectedValue(new Error("x"));
    renderViewer({ loadFile: vi.fn().mockResolvedValue(file({ archived: true })), restore });
    await ready();
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(await screen.findByText("Couldn't restore. Try again.")).toBeInTheDocument();
    expect(screen.getByText("Archived · read-only")).toBeInTheDocument();
  });

  it("opens at initialPage", async () => {
    renderViewer({ initialPage: 3 });
    expect(await screen.findByText("p. 3 / 3")).toBeInTheDocument();
  });

  it("moves to the page of each new jumpTo, keeping the loaded PDF", async () => {
    const { rerender, props, loadPdfDoc } = renderViewer();
    await ready();
    rerender(<DocumentViewer {...props} jumpTo={{ page: 3 }} />);
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Previous page" }));
    rerender(<DocumentViewer {...props} jumpTo={{ page: 3 }} />);
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    rerender(<DocumentViewer {...props} jumpTo={{ page: 9 }} />);
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    expect(loadPdfDoc).toHaveBeenCalledTimes(1);
  });

  it("ignores a late load of a document that was swapped out", async () => {
    const first = deferred<PdfDoc>();
    const late = pdf(3);
    const loadFile = vi.fn(async (id: string) => file({ document_id: id, title: id === "d1" ? "ReAct" : "PPO" }, `url-${id}`));
    const loadPdfDoc = vi.fn((url: string) => (url === "url-d1" ? first.promise : Promise.resolve(pdf(5))));
    const { rerender, props } = renderViewer({ loadFile, loadPdfDoc });
    await waitFor(() => expect(loadPdfDoc).toHaveBeenCalledWith("url-d1"));
    rerender(<DocumentViewer {...props} documentId="d2" />);
    expect(await screen.findByText("p. 1 / 5")).toBeInTheDocument();
    await act(async () => first.resolve(late));
    expect(screen.getByText("p. 1 / 5")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "PPO" })).toBeInTheDocument();
    expect(late.destroy).toHaveBeenCalled();
  });

  it("does not reload the PDF when the link is renewed", async () => {
    // Fake time makes the order fixed: the PDF loads from u1 first, and only then does the renewal timer fire.
    vi.useFakeTimers();
    vi.setSystemTime(0);
    try {
      const loadFile = vi
        .fn()
        .mockResolvedValueOnce(file({}, "u1", 300_000))
        .mockResolvedValue(file({}, "u2", 600_000));
      const { loadPdfDoc } = renderViewer({ loadFile });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText("p. 1 / 3")).toBeInTheDocument();
      expect(loadPdfDoc).toHaveBeenCalledTimes(1);
      expect(loadPdfDoc).toHaveBeenCalledWith("u1");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(271_000); // past expiresAt - 30s
      });
      expect(loadFile).toHaveBeenCalledTimes(2);
      expect(loadPdfDoc).toHaveBeenCalledTimes(1);
      expect(loadPdfDoc).not.toHaveBeenCalledWith("u2");
    } finally {
      vi.useRealTimers();
    }
  });

  it("destroys the PDF when it closes", async () => {
    const loaded = pdf();
    const { unmount } = renderViewer({ loadPdfDoc: vi.fn().mockResolvedValue(loaded) });
    await ready();
    unmount();
    expect(loaded.destroy).toHaveBeenCalled();
  });

  it("closes, and opens in a dialog at the current page", async () => {
    const onOpenInDialog = vi.fn();
    const { onClose } = renderViewer({ onOpenInDialog });
    await ready();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await userEvent.click(screen.getByRole("button", { name: "Open in dialog" }));
    expect(onOpenInDialog).toHaveBeenCalledWith(2);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("in a dialog, starts with the back button and shows the details strip", async () => {
    const onClose = vi.fn();
    renderViewer({
      mode: "dialog",
      closeLabel: "Back to side by side",
      showDetails: true,
      onClose,
      loadFile: vi.fn().mockResolvedValue(file({ authors: ["Yao", "Zhao"], subjects: [{ subject_id: "s1", name: "AI Agents" }] as DocumentResponse["subjects"] })),
    });
    await ready();
    expect(screen.queryByRole("button", { name: "Open in dialog" })).not.toBeInTheDocument();
    expect(screen.getByText("Yao, Zhao")).toBeInTheDocument();
    expect(screen.getByText("2022")).toBeInTheDocument();
    expect(screen.getByText("3 pages")).toBeInTheDocument();
    expect(screen.getByText("AI Agents")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back to side by side" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("offers no download", async () => {
    renderViewer({ onOpenInDialog: vi.fn() });
    await ready();
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /download/i })).not.toBeInTheDocument();
  });
});
