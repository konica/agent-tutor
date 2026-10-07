import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DropOverlay } from "./DropOverlay";
import { usePageDrop } from "./usePageDrop";

function Page({ onFiles }: { onFiles: (files: File[]) => void }) {
  const active = usePageDrop(onFiles);
  return (
    <div>
      <p>Library</p>
      {active && <DropOverlay />}
    </div>
  );
}

const withFiles = (files: File[] = []) => ({ dataTransfer: { types: ["Files"], files } });
const textOnly = { dataTransfer: { types: ["text/plain"], files: [] } };

describe("usePageDrop", () => {
  it("highlights the page while files are dragged over it and clears on leave", () => {
    render(<Page onFiles={vi.fn()} />);
    fireEvent.dragEnter(document.body, withFiles());
    expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
    fireEvent.dragLeave(document.body, withFiles());
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
  });

  it("stays highlighted while the drag moves between child elements", () => {
    render(<Page onFiles={vi.fn()} />);
    const child = screen.getByText("Library");
    fireEvent.dragEnter(document.body, withFiles());
    fireEvent.dragEnter(child, withFiles());
    fireEvent.dragLeave(document.body, withFiles());
    expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
    fireEvent.dragLeave(child, withFiles());
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
  });

  it("clears the highlight after dragging out of all elements", () => {
    render(<Page onFiles={vi.fn()} />);
    const child = screen.getByText("Library");
    fireEvent.dragEnter(document.body, withFiles());
    fireEvent.dragEnter(child, withFiles());
    expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
    // Simulate drag leaving by firing balanced dragLeave events
    fireEvent.dragLeave(child, withFiles());
    expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument(); // still showing after leaving child
    fireEvent.dragLeave(document.body, withFiles());
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull(); // now hidden after leaving body
  });

  it("hands the dropped files over and clears the highlight", () => {
    const onFiles = vi.fn();
    render(<Page onFiles={onFiles} />);
    const a = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    const b = new File(["x"], "b.docx");
    fireEvent.dragEnter(document.body, withFiles());
    const drop = fireEvent.drop(document.body, withFiles([a, b]));
    expect(drop).toBe(false); // default prevented: the browser must not open the file
    expect(onFiles).toHaveBeenCalledWith([a, b]);
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
  });

  it("prevents the default on drag-over so the page accepts the drop", () => {
    render(<Page onFiles={vi.fn()} />);
    expect(fireEvent.dragOver(document.body, withFiles())).toBe(false);
  });

  it("ignores drags without files", () => {
    const onFiles = vi.fn();
    render(<Page onFiles={onFiles} />);
    fireEvent.dragEnter(document.body, textOnly);
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
    expect(fireEvent.drop(document.body, textOnly)).toBe(true);
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("stops listening when the page unmounts", () => {
    const onFiles = vi.fn();
    const { unmount } = render(<Page onFiles={onFiles} />);
    unmount();
    expect(fireEvent.drop(document.body, withFiles([new File(["%PDF"], "a.pdf")]))).toBe(true);
    expect(onFiles).not.toHaveBeenCalled();
  });
});
