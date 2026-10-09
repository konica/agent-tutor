import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UploadTray, type TrayItem } from "./UploadTray";

const uploading: TrayItem = { id: "1", name: "lewis-rag-2020.pdf", size: "0.9 MB", status: "uploading", progress: 0.42 };
const uploaded: TrayItem = { id: "2", name: "react-yao-2022.pdf", size: "3.1 MB", status: "uploaded", progress: 1 };
const failed: TrayItem = { id: "3", name: "big.pdf", size: "2.2 MB", status: "failed", progress: 0.3 };

describe("UploadTray", () => {
  it("renders nothing without items", () => {
    const { container } = render(<UploadTray items={[]} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a labelled progress bar for each uploading file and no Close while busy", () => {
    render(<UploadTray items={[uploading, { ...uploading, id: "4", name: "b.pdf", progress: 0, size: "1.2 MB" }]} onClose={vi.fn()} />);
    const tray = screen.getByRole("region", { name: "Uploading 2 files…" });
    const bar = within(tray).getByRole("progressbar", { name: "Upload progress for lewis-rag-2020.pdf" });
    expect(bar).toHaveAttribute("aria-valuenow", "42");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(within(tray).getByText("Uploading · 0.9 MB")).toBeVisible();
    expect(within(tray).getAllByRole("progressbar")).toHaveLength(2);
    expect(within(tray).queryByRole("button", { name: "Close uploads" })).toBeNull();
  });

  it("counts only uploading files in the busy header, singular for one", () => {
    render(<UploadTray items={[uploading, uploaded]} onClose={vi.fn()} />);
    expect(screen.getByRole("region", { name: "Uploading 1 file…" })).toBeVisible();
  });

  it("says uploaded or failed when done, and offers Close", async () => {
    const onClose = vi.fn();
    render(<UploadTray items={[uploaded, failed]} onClose={onClose} />);
    const tray = screen.getByRole("region", { name: "Uploads · 2 files" });
    expect(within(tray).getByText("Uploaded · processing")).toBeVisible();
    expect(within(tray).getByText("Upload failed")).toBeVisible();
    expect(within(tray).queryByRole("progressbar")).toBeNull();
    await userEvent.click(within(tray).getByRole("button", { name: "Close uploads" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("says a server-found duplicate is already in the library and links to it", () => {
    render(<UploadTray items={[{ ...uploaded, status: "already", documentId: "d1", archived: false }]} onClose={vi.fn()} />);
    const tray = screen.getByRole("region", { name: "Uploads · 1 file" });
    expect(within(tray).getByText("Already in your library")).toBeVisible();
    expect(within(tray).getByRole("link", { name: "Open document" })).toHaveAttribute("href", "#document-d1");
  });

  it("says an archived duplicate is archived, without a link", () => {
    render(<UploadTray items={[{ ...uploaded, status: "already", documentId: "d1", archived: true }]} onClose={vi.fn()} />);
    expect(screen.getByText("Already in your library, archived")).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("collapses and expands the list by keyboard", async () => {
    render(<UploadTray items={[uploaded]} onClose={vi.fn()} />);
    const toggle = screen.getByRole("button", { name: "Collapse uploads" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    toggle.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.queryByText("react-yao-2022.pdf")).toBeNull();
    const expand = screen.getByRole("button", { name: "Expand uploads" });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    expect(expand).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByText("react-yao-2022.pdf")).toBeVisible();
  });

  it("moves focus to the toggle when a new upload removes the focused Close button", () => {
    const { rerender } = render(<UploadTray items={[uploaded]} onClose={vi.fn()} />);
    screen.getByRole("button", { name: "Close uploads" }).focus();
    rerender(<UploadTray items={[uploading, uploaded]} onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Collapse uploads" })).toHaveFocus();
  });

  it("leaves focus alone when Close was not focused", () => {
    const { rerender } = render(<UploadTray items={[uploaded]} onClose={vi.fn()} />);
    rerender(<UploadTray items={[uploading, uploaded]} onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Collapse uploads" })).not.toHaveFocus();
  });

  it("reopens expanded after it was collapsed and closed", async () => {
    const { rerender } = render(<UploadTray items={[uploaded]} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Collapse uploads" }));
    expect(screen.queryByText("react-yao-2022.pdf")).toBeNull();
    rerender(<UploadTray items={[]} onClose={vi.fn()} />);
    rerender(<UploadTray items={[uploading]} onClose={vi.fn()} />);
    expect(screen.getByText("lewis-rag-2020.pdf")).toBeVisible();
  });
});
