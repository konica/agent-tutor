import { useEffect, useRef, useState } from "react";

const carriesFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes("Files");
const DRAG_IDLE_MS = 1000;

// The whole page accepts dropped files while the Library is mounted (brief §6.3). Dragging over child elements fires
// dragenter/dragleave pairs, so a depth count decides when the drag has really left; if no dragover arrives for
// DRAG_IDLE_MS, the drag ended elsewhere (cancelled or left the window). Drags without files are left alone.
export function usePageDrop(onFiles: (files: File[]) => void): boolean {
  const [active, setActive] = useState(false);
  const onFilesRef = useRef(onFiles);
  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    onFilesRef.current = onFiles;
  }, [onFiles]);

  const clearIdleTimer = () => {
    if (idleTimerRef.current) {
      clearTimeout(idleTimerRef.current);
      idleTimerRef.current = null;
    }
  };

  const resetIdleTimer = () => {
    clearIdleTimer();
    idleTimerRef.current = setTimeout(() => {
      idleTimerRef.current = null;
      // No dragover for DRAG_IDLE_MS means the drag ended
      setActive(false);
    }, DRAG_IDLE_MS);
  };

  useEffect(() => {
    let depth = 0;
    const enter = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth++;
      setActive(true);
      resetIdleTimer();
    };
    const over = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      resetIdleTimer();
    };
    const leave = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) {
        setActive(false);
        clearIdleTimer();
      }
    };
    const drop = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setActive(false);
      clearIdleTimer();
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length) onFilesRef.current(files);
    };
    document.addEventListener("dragenter", enter);
    document.addEventListener("dragover", over);
    document.addEventListener("dragleave", leave);
    document.addEventListener("drop", drop);
    return () => {
      document.removeEventListener("dragenter", enter);
      document.removeEventListener("dragover", over);
      document.removeEventListener("dragleave", leave);
      document.removeEventListener("drop", drop);
      clearIdleTimer();
    };
  }, []);

  return active;
}
