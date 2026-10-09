import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RefObject } from "react";
import { describe, expect, it, vi } from "vitest";

import { fakeViewerDeps } from "./testFakes";
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
});
