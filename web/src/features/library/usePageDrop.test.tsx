import { act, fireEvent, render, screen } from "@testing-library/react";
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

  it("clears the highlight when the drag is cancelled or leaves the window", () => {
    vi.useFakeTimers();
    try {
      render(<Page onFiles={vi.fn()} />);
      const child = screen.getByText("Library");
      fireEvent.dragEnter(document.body, withFiles());
      fireEvent.dragEnter(child, withFiles());
      expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
      // Simulate unbalanced dragleave: drag was cancelled or left the window
      fireEvent.dragLeave(child, withFiles());
      // Overlay still showing, but idle timer is ticking
      expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
      // Advance time past the idle threshold
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      // Now the overlay should be gone
      expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("stays highlighted while dragover keeps arriving", () => {
    vi.useFakeTimers();
    try {
      render(<Page onFiles={vi.fn()} />);
      fireEvent.dragEnter(document.body, withFiles());
      expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
      // Advance time but stay below the idle threshold
      act(() => {
        vi.advanceTimersByTime(900);
      });
      // Send another dragover to reset the idle timer
      fireEvent.dragOver(document.body, withFiles());
      // Overlay still showing
      expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
      // Advance another 900ms (total 1800ms, but timer was reset)
      act(() => {
        vi.advanceTimersByTime(900);
      });
      // Overlay should still be showing because dragover keeps resetting the timer
      expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
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
