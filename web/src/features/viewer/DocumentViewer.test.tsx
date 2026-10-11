import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentNotFoundError, DocumentNotOpenableError, type DocumentResponse } from "../../api/documents";
import type { ChunkPassage } from "../../api/chunks";
import { DocumentViewer, type Passage } from "./DocumentViewer";
import type { TextItem } from "./passage";
import type { PdfDoc, PdfPage } from "./pdf";
import { GESTURE_GAP_MS } from "./usePageFlip";
import { fakeDocument, fakeFile, fakePdf, fakeViewerDeps } from "./testFakes";

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
    expect(screen.getByRole("img", { name: "Page 1 of 3" }).tagName).toBe("CANVAS");
  });

  it("pages with the buttons and PageDown/PageUp, and announces the page", async () => {
    const onPageChange = vi.fn();
    renderViewer({ onPageChange });
    await ready();
    const previous = screen.getByRole("button", { name: "Previous page" });
    expect(previous).toHaveAttribute("aria-disabled", "true");
    expect(previous).not.toBeDisabled(); // focusable: a disabled button would drop focus to <body>
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
    expect(screen.getByRole("button", { name: "Next page" })).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
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
    expect(zoomIn).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(zoomIn);
    expect(screen.getByText("200%")).toBeInTheDocument();
    for (let i = 0; i < 5; i++) await userEvent.click(zoomOut);
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(zoomOut).toHaveAttribute("aria-disabled", "true");
    expect(zoomIn).not.toHaveAttribute("aria-disabled");
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

  it("says a document no longer in the library is gone, without Retry", async () => {
    renderViewer({ loadFile: vi.fn().mockRejectedValue(new DocumentNotFoundError("Document not found")) });
    expect(await screen.findByText("This document is no longer in your library.")).toBeInTheDocument();
    expect(screen.queryByText("Check your connection and try again.")).not.toBeInTheDocument();
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
    // The Restore button is gone; focus moves to the title instead of dropping to <body>.
    expect(screen.getByRole("heading", { level: 2, name: "ReAct" })).toHaveFocus();
  });

  it("keeps focus on Restore while it is in flight", async () => {
    const pending = deferred<DocumentResponse>();
    renderViewer({ loadFile: vi.fn().mockResolvedValue(file({ archived: true })), restore: vi.fn(() => pending.promise) });
    await ready();
    const restoreButton = screen.getByRole("button", { name: "Restore" });
    restoreButton.focus();
    await userEvent.keyboard("{Enter}");
    expect(restoreButton).toHaveAttribute("aria-disabled", "true");
    expect(restoreButton).toHaveFocus();
    await act(async () => pending.resolve(doc()));
    expect(screen.getByRole("heading", { level: 2, name: "ReAct" })).toHaveFocus();
  });

  it("keeps focus on Next when Enter reaches the last page", async () => {
    renderViewer();
    await ready();
    const next = screen.getByRole("button", { name: "Next page" });
    next.focus();
    await userEvent.keyboard("{Enter}{Enter}");
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    expect(next).toHaveAttribute("aria-disabled", "true");
    expect(next).toHaveFocus();
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

// Page items: the first chunk's text on one line at y 300, the second chunk's at y 400.
const CITED: TextItem = { str: "Cited text here.", hasEOL: true, x: 50, y: 300, width: 200, height: 12 };
const SECOND: TextItem = { str: "Second passage.", hasEOL: true, x: 60, y: 400, width: 150, height: 12 };
const OTHER: TextItem = { str: "Something else entirely.", hasEOL: true, x: 50, y: 100, width: 220, height: 12 };

const chunk = (id: string, page: number, text: string): ChunkPassage => ({ chunkId: id, documentId: "d1", page, startIndex: 0, text });

function renderCited(items: TextItem[], props: Partial<Props> = {}) {
  const deps = fakeViewerDeps();
  deps.loadPdfDoc.mockImplementation(async () => fakePdf(3, items));
  const passage: Passage = { chunkId: "c1", page: 2 };
  const all: Props = { documentId: "d1", mode: "pane", onClose: vi.fn(), ...deps, passage, ...props };
  const view = render(<DocumentViewer {...all} />);
  return { ...view, ...deps, ...all, props: all };
}

const status = () => document.querySelector("[aria-live=polite]")!;
const boxes = () => screen.queryAllByTestId("passage-box");

describe("DocumentViewer citation highlight", () => {
  it("a citation opens its page with the passage highlighted", async () => {
    const { recordMiss, loadChunk } = renderCited([OTHER, CITED]);
    expect(await screen.findByText("p. 2 / 3")).toBeInTheDocument();
    expect(await screen.findByTestId("passage-box")).toBeInTheDocument();
    expect(loadChunk).toHaveBeenCalledWith("c1");
    expect(screen.getByText("Cited passage")).toBeInTheDocument();
    expect(screen.getByText("Cited passage begins. Cited text here. Cited passage ends.")).toBeInTheDocument();
    await waitFor(() => expect(status()).toHaveTextContent("Opened page 2 of 3. Cited passage highlighted."));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(recordMiss).not.toHaveBeenCalled();
  });

  it("draws the boxes and the label out of the accessibility tree", async () => {
    renderCited([CITED]);
    const box = await screen.findByTestId("passage-box");
    expect(box.closest("[aria-hidden=true]")).not.toBeNull();
    expect(screen.getByText("Cited passage").closest("[aria-hidden=true]")).not.toBeNull();
    expect(screen.getByText(/Cited passage begins\./).closest("[aria-hidden=true]")).toBeNull();
    expect(box.style.left).toBe("50px");
    expect(box.style.top).toBe("300px");
    expect(box.style.height).toBe("12px");
  });

  it("no match shows the page with the note", async () => {
    const { recordMiss, rerender, props } = renderCited([OTHER]);
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("Couldn't highlight the passage on this page.");
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    expect(boxes()).toHaveLength(0);
    await waitFor(() => expect(status()).toHaveTextContent("Opened page 2 of 3. Couldn't highlight the passage on this page."));
    expect(recordMiss).toHaveBeenCalledTimes(1);
    rerender(<DocumentViewer {...props} />);
    await act(async () => {});
    expect(recordMiss).toHaveBeenCalledTimes(1);
  });

  it("a failed chunk request shows the page without highlight", async () => {
    const loadChunk = vi.fn().mockRejectedValue(new Error("offline"));
    const { recordMiss } = renderCited([CITED], { loadChunk });
    expect(await screen.findByRole("note")).toHaveTextContent("Couldn't highlight the passage on this page.");
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    expect(boxes()).toHaveLength(0);
    expect(recordMiss).toHaveBeenCalledTimes(1);
  });

  it("a second chip of the same document moves the highlight", async () => {
    const loadChunk = vi.fn(async (id: string) => (id === "c2" ? chunk("c2", 3, "Second passage.") : chunk("c1", 2, "Cited text here.")));
    const { rerender, props, loadPdfDoc } = renderCited([CITED, SECOND], { loadChunk });
    const first = await screen.findByTestId("passage-box");
    expect(first.style.top).toBe("300px");
    rerender(<DocumentViewer {...props} passage={{ chunkId: "c2", page: 3 }} />);
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    expect(boxes()).toHaveLength(0);
    await waitFor(() => expect(boxes()).toHaveLength(1));
    expect(boxes()[0]!.style.top).toBe("400px");
    await waitFor(() => expect(status()).toHaveTextContent("Opened page 3 of 3. Cited passage highlighted."));
    expect(loadPdfDoc).toHaveBeenCalledTimes(1);
  });

  it("a late chunk of a swapped-out passage is ignored", async () => {
    let resolveFirst!: (c: ChunkPassage) => void;
    const loadChunk = vi.fn((id: string) =>
      id === "c1" ? new Promise<ChunkPassage>((r) => (resolveFirst = r)) : Promise.resolve(chunk("c2", 2, "Not on the page.")),
    );
    const { rerender, props } = renderCited([CITED], { loadChunk });
    await screen.findByText("p. 2 / 3");
    rerender(<DocumentViewer {...props} passage={{ chunkId: "c2", page: 2 }} />);
    expect(await screen.findByRole("note")).toBeInTheDocument();
    await act(async () => resolveFirst(chunk("c1", 2, "Cited text here.")));
    expect(boxes()).toHaveLength(0);
    expect(screen.getByRole("note")).toBeInTheDocument();
  });

  it("the highlight follows zoom", async () => {
    renderCited([CITED]);
    const box = await screen.findByTestId("passage-box");
    expect(box.style.width).toBe("200px");
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("125%")).toBeInTheDocument();
    expect(screen.getByTestId("passage-box").style.width).toBe("250px");
    expect(screen.getByTestId("passage-box").style.top).toBe("375px");
  });

  it("the highlight shows only on its page", async () => {
    const { container, recordMiss } = renderCited([CITED]);
    await screen.findByTestId("passage-box");
    const area = container.querySelector<HTMLElement>(".canvasArea")!;
    area.scrollTop = 10; // the learner scrolls away
    const title = screen.getByRole("heading", { level: 2 });
    fireEvent.keyDown(title, { key: "PageDown" });
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    expect(boxes()).toHaveLength(0);
    expect(screen.queryByText(/Cited passage begins/)).not.toBeInTheDocument();
    await waitFor(() => expect(status()).toHaveTextContent(/^Page 3 of 3$/));
    fireEvent.keyDown(title, { key: "PageUp" });
    expect(await screen.findByTestId("passage-box")).toBeInTheDocument();
    await waitFor(() => expect(status()).toHaveTextContent(/^Page 2 of 3$/));
    expect(area.scrollTop).toBe(10); // scrolled once per passage, not on every return
    expect(recordMiss).not.toHaveBeenCalled();
  });

  it("scrolls the passage to a third from the top", async () => {
    const clientHeight = vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(600);
    const offsetTop = vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockReturnValue(40);
    try {
      const { container } = renderCited([CITED]);
      await screen.findByTestId("passage-box");
      const area = container.querySelector<HTMLElement>(".canvasArea")!;
      await waitFor(() => expect(area.scrollTop).toBe(40 + 300 * 1 - 600 / 3));
    } finally {
      clientHeight.mockRestore();
      offsetTop.mockRestore();
    }
  });

  it("scrolls a passage beyond the visible width into view sideways", async () => {
    const clientHeight = vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(600);
    const clientWidth = vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(100);
    const offsetTop = vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockReturnValue(40);
    const offsetLeft = vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockReturnValue(40);
    try {
      const { container } = renderCited([CITED]);
      await screen.findByTestId("passage-box");
      const area = container.querySelector<HTMLElement>(".canvasArea")!;
      // the page's left margin + the passage's x - the 4px marker gap - a 16px margin
      await waitFor(() => expect(area.scrollLeft).toBe(40 + 50 * 1 - 4 - 16));
    } finally {
      clientHeight.mockRestore();
      clientWidth.mockRestore();
      offsetTop.mockRestore();
      offsetLeft.mockRestore();
    }
  });

  it("leaves the horizontal scroll alone when the passage is already in view", async () => {
    const clientHeight = vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(600);
    const clientWidth = vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(1000);
    const offsetTop = vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockReturnValue(40);
    const offsetLeft = vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockReturnValue(40);
    try {
      const { container } = renderCited([CITED]);
      await screen.findByTestId("passage-box");
      const area = container.querySelector<HTMLElement>(".canvasArea")!;
      await waitFor(() => expect(area.scrollTop).toBe(40 + 300 * 1 - 600 / 3)); // the reveal has run
      expect(area.scrollLeft).toBe(0);
    } finally {
      clientHeight.mockRestore();
      clientWidth.mockRestore();
      offsetTop.mockRestore();
      offsetLeft.mockRestore();
    }
  });

  it("does not scroll above the top", async () => {
    const clientHeight = vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(1200);
    try {
      const { container } = renderCited([CITED]);
      await screen.findByTestId("passage-box");
      expect(container.querySelector<HTMLElement>(".canvasArea")!.scrollTop).toBe(0);
    } finally {
      clientHeight.mockRestore();
    }
  });

  it("an explicit initialPage wins over the passage's page", async () => {
    renderCited([CITED], { initialPage: 3 });
    expect(await screen.findByText("p. 3 / 3")).toBeInTheDocument();
    await waitFor(() => expect(status()).toHaveTextContent(/^Page 3 of 3$/));
    expect(boxes()).toHaveLength(0);
  });

  it("without a passage, asks for no chunk and announces the page", async () => {
    const { loadChunk } = renderCited([CITED], { passage: undefined });
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    expect(loadChunk).not.toHaveBeenCalled();
    expect(boxes()).toHaveLength(0);
  });
});

// The canvas area as the learner scrolls it: a 600px window over a 2000px page (or a page that fits), at `top`.
function scrollArea(height = 2000) {
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(600);
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockReturnValue(height);
}
const area = () => document.querySelector<HTMLElement>(".canvasArea")!;

describe("DocumentViewer flip at the edge", () => {
  let now = 1_000_000;
  const wheel = (deltaY: number) => {
    now += 16;
    return fireEvent.wheel(area(), { deltaY });
  };
  const pause = () => (now += GESTURE_GAP_MS + 100);
  // Lets the flipped-to page render (the fake PDF resolves in microtasks); until then a pending landing blocks a flip.
  const rendered = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));
  // A 3-page PDF whose page 2 loads only when `page2.resolve` is called.
  function slowPage2() {
    const fake = pdf();
    const fast = fake.page;
    const page2 = deferred<PdfPage>();
    fake.page = vi.fn((n: number) => (n === 2 ? page2.promise : fast(n)));
    return { fake, page2, fast };
  }
  beforeEach(() => {
    vi.spyOn(Date, "now").mockImplementation(() => now);
  });
  afterEach(() => vi.restoreAllMocks());

  it("scrolling down past the bottom opens the next page at its top", async () => {
    scrollArea();
    const onPageChange = vi.fn();
    const onOpenInDialog = vi.fn();
    renderViewer({ onPageChange, onOpenInDialog });
    await ready();
    area().scrollTop = 1400;
    wheel(100);
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    expect(onPageChange).toHaveBeenLastCalledWith(2);
    await waitFor(() => expect(area().scrollTop).toBe(0));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open in dialog" }));
    expect(onOpenInDialog).toHaveBeenCalledWith(2);
  });

  it("scrolling up past the top opens the previous page at its bottom", async () => {
    scrollArea();
    renderViewer({ initialPage: 3 });
    expect(await screen.findByText("p. 3 / 3")).toBeInTheDocument();
    area().scrollTop = 0;
    wheel(-100);
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    await waitFor(() => expect(area().scrollTop).toBe(2000 - 600));
  });

  it("the gesture that reaches the bottom doesn't flip; one more gesture flips one page", async () => {
    scrollArea();
    renderViewer();
    await ready();
    area().scrollTop = 1300;
    wheel(100);
    area().scrollTop = 1400; // the browser scrolled to the bottom
    for (let i = 0; i < 20; i++) wheel(100);
    expect(screen.getByText("p. 1 / 3")).toBeInTheDocument();
    pause();
    for (let i = 0; i < 20; i++) wheel(100); // a flick with momentum
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
  });

  it("a page with no scrollbar flips on one gesture either way", async () => {
    scrollArea(600);
    renderViewer();
    await ready();
    wheel(100);
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    await rendered();
    pause();
    wheel(-100);
    expect(screen.getByText("p. 1 / 3")).toBeInTheDocument();
  });

  it("nothing happens past the first or last page", async () => {
    scrollArea(600);
    const onPageChange = vi.fn();
    renderViewer({ onPageChange });
    await ready();
    wheel(-100);
    expect(screen.getByText("p. 1 / 3")).toBeInTheDocument();
    for (let i = 0; i < 3; i++) {
      pause();
      wheel(100);
      await rendered();
    }
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    expect(onPageChange.mock.calls).toEqual([[2], [3]]);
  });

  it("PageDown keeps the scroll position (no landing)", async () => {
    scrollArea();
    renderViewer();
    await ready();
    area().scrollTop = 700;
    fireEvent.keyDown(screen.getByRole("heading", { level: 2 }), { key: "PageDown" });
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    expect(area().scrollTop).toBe(700);
  });

  it("PageDown before the flipped-to page renders drops its landing", async () => {
    scrollArea();
    const { fake, page2, fast } = slowPage2();
    renderViewer({ loadPdfDoc: vi.fn().mockResolvedValue(fake) });
    await ready();
    area().scrollTop = 1400;
    wheel(100);
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("heading", { level: 2 }), { key: "PageDown" });
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    page2.resolve(await fast(2));
    await rendered();
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument();
    expect(area().scrollTop).toBe(1400);
  });

  it("another gesture while the flipped-to page loads doesn't turn a page the learner hasn't seen", async () => {
    scrollArea();
    const { fake, page2, fast } = slowPage2();
    renderViewer({ loadPdfDoc: vi.fn().mockResolvedValue(fake) });
    await ready();
    area().scrollTop = 1400;
    wheel(100);
    pause();
    expect(wheel(100)).toBe(false); // swallowed
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    page2.resolve(await fast(2));
    await waitFor(() => expect(area().scrollTop).toBe(0));
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
  });

  it("the citation reveal's scroll never flips", async () => {
    // The reveal scrolls the passage to a third from the top: 40 + 300 - 600 / 3 = 140, the bottom of a 740px page.
    scrollArea(740);
    vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockReturnValue(40);
    renderCited([CITED]);
    await screen.findByTestId("passage-box");
    await waitFor(() => expect(area().scrollTop).toBe(140));
    fireEvent.scroll(area()); // guards against a future scroll listener: the hook counts only wheel and touch
    await waitFor(() => expect(status()).toHaveTextContent("Opened page 2 of 3. Cited passage highlighted."));
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
  });
});
