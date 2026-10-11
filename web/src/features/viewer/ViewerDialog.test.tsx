import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RefObject } from "react";
import { describe, expect, it, vi } from "vitest";

import { fakeDocument, fakeFile, fakeViewerDeps } from "./testFakes";
import { ViewerDialog } from "./ViewerDialog";

function open(props: { onClose?: (page: number) => void; returnFocusTo?: RefObject<HTMLElement | null> } = {}) {
  const onClose = props.onClose ?? vi.fn();
  const view = render(
    <ViewerDialog documentId="d1" closeLabel="Close" onClose={onClose} returnFocusTo={props.returnFocusTo} viewerDeps={fakeViewerDeps()} />,
  );
  return { ...view, onClose };
}

const ready = () => screen.findByText("p. 1 / 3");

describe("ViewerDialog", () => {
  it("is a modal dialog named by the document title, with the title focused", async () => {
    open();
    await ready();
    const dialog = screen.getByRole("dialog", { name: "ReAct" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("heading", { level: 2, name: "ReAct" })).toHaveFocus();
  });

  it("traps Tab: the last control wraps to the first and back", async () => {
    open();
    await ready();
    const dialog = screen.getByRole("dialog");
    const first = screen.getByRole("button", { name: "Close" });
    const last = screen.getByRole("button", { name: "Zoom in" });
    last.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("closes on Escape with the current page", async () => {
    const { onClose } = open();
    await ready();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledWith(2);
  });

  it("keeps focus inside when Next reaches the last page: Tab wraps and Escape still closes", async () => {
    const { onClose } = open();
    await ready();
    const dialog = screen.getByRole("dialog");
    const next = screen.getByRole("button", { name: "Next page" });
    next.focus();
    await userEvent.keyboard("{Enter}{Enter}");
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    expect(next).toHaveFocus();
    await userEvent.tab(); // Zoom out
    await userEvent.tab(); // Zoom in, the last control
    await userEvent.tab(); // wraps to the first
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledWith(3);
  });

  it("shows the details strip", async () => {
    open();
    await ready();
    expect(screen.getByText("Yao")).toBeInTheDocument();
    expect(screen.getByText("2022")).toBeInTheDocument();
    expect(screen.getByText("3 pages")).toBeInTheDocument();
  });

  it("restores an archived document in place and reports it with onRestored", async () => {
    const deps = { ...fakeViewerDeps(), loadFile: vi.fn(async () => fakeFile({ archived: true })), restore: vi.fn(async () => fakeDocument()) };
    const onRestored = vi.fn();
    render(<ViewerDialog documentId="d1" closeLabel="Close" onClose={vi.fn()} onRestored={onRestored} viewerDeps={deps} />);
    expect(await screen.findByText("Archived · read-only")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(onRestored).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ document_id: "d1", archived: false })));
    expect(deps.restore).toHaveBeenCalledWith("d1");
    expect(screen.queryByText("Archived · read-only")).toBeNull();
    expect(screen.getByRole("dialog", { name: "ReAct" })).toBeVisible();
    expect(within(screen.getByRole("dialog", { name: "ReAct" })).getByText("Document restored.")).toBeInTheDocument(); // announced inside the modal
  });

  it("shows the restore error and does not report onRestored when the restore fails", async () => {
    const restore = vi.fn(async () => {
      throw new Error("nope");
    });
    const deps = { ...fakeViewerDeps(), loadFile: vi.fn(async () => fakeFile({ archived: true })), restore };
    const onRestored = vi.fn();
    render(<ViewerDialog documentId="d1" closeLabel="Close" onClose={vi.fn()} onRestored={onRestored} viewerDeps={deps} />);
    await userEvent.click(await screen.findByRole("button", { name: "Restore" }));
    expect(await screen.findByText("Couldn't restore. Try again.")).toBeVisible();
    expect(restore).toHaveBeenCalledWith("d1");
    expect(onRestored).not.toHaveBeenCalled();
    expect(screen.queryByText("Document restored.")).toBeNull();
  });

  it("returns focus to returnFocusTo when it closes", async () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    const returnFocusTo: RefObject<HTMLElement | null> = { current: opener };
    const { unmount } = open({ returnFocusTo });
    await ready();
    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("flips at the edge and closes with the flipped page", async () => {
    vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(600);
    vi.spyOn(Element.prototype, "scrollHeight", "get").mockReturnValue(600);
    try {
      const { onClose } = open();
      await ready();
      fireEvent.wheel(document.querySelector(".canvasArea")!, { deltaY: 100 });
      expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
      fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
      expect(onClose).toHaveBeenCalledWith(2);
    } finally {
      vi.restoreAllMocks();
    }
  });
});
