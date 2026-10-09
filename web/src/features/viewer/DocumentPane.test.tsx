import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DocumentPane } from "./DocumentPane";
import { fakeViewerDeps } from "./testFakes";

function renderPane(documentId = "d1") {
  const onClose = vi.fn();
  const viewerDeps = fakeViewerDeps();
  const view = render(<DocumentPane documentId={documentId} onClose={onClose} viewerDeps={viewerDeps} />);
  return { ...view, onClose, viewerDeps };
}

const ready = () => screen.findByText("p. 1 / 3");

describe("DocumentPane", () => {
  it("is a region named by the document title", async () => {
    renderPane();
    await ready();
    expect(screen.getByRole("region", { name: "ReAct" })).toBeInTheDocument();
  });

  it("focuses the title on open and again when the document is swapped", async () => {
    const { rerender, onClose, viewerDeps } = renderPane();
    await ready();
    expect(screen.getByRole("heading", { level: 2, name: "ReAct" })).toHaveFocus();
    screen.getByRole("button", { name: "Next page" }).focus();
    rerender(<DocumentPane documentId="d2" onClose={onClose} viewerDeps={viewerDeps} />);
    const title = await screen.findByRole("heading", { level: 2, name: "PPO" });
    expect(title).toHaveFocus();
  });

  it("closes on Escape", async () => {
    const { onClose } = renderPane();
    await ready();
    fireEvent.keyDown(screen.getByRole("heading", { level: 2, name: "ReAct" }), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("opens the dialog at the pane's page; Escape closes only the dialog and refocuses Open in dialog", async () => {
    const { onClose } = renderPane();
    await ready();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await userEvent.click(screen.getByRole("button", { name: "Open in dialog" }));
    const dialog = await screen.findByRole("dialog", { name: "ReAct" });
    expect(await within(dialog).findByText("p. 2 / 3")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Back to side by side" })).toBeInTheDocument();
    fireEvent.keyDown(within(dialog).getByRole("heading", { level: 2 }), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Open in dialog" })).toHaveFocus();
  });

  it("jumps to the dialog's last page when the dialog closes", async () => {
    const { viewerDeps } = renderPane();
    await ready();
    await userEvent.click(screen.getByRole("button", { name: "Open in dialog" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("p. 1 / 3");
    await userEvent.click(within(dialog).getByRole("button", { name: "Next page" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Next page" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Back to side by side" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    // The pane kept its PDF: only the dialog loaded a second copy.
    expect(viewerDeps.loadPdfDoc).toHaveBeenCalledTimes(2);
  });
});
