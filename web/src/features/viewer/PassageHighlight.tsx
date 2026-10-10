import styles from "./DocumentViewer.module.css";
import type { Box } from "./passage";

type Props = { boxes: Box[]; scale: number; text: string }; // boxes in CSS px at zoom 100%, one per line; at least one

export const MARKER_GAP = 4; // px between the marker and the passage's left edge

// The cited passage over the canvas (DESIGN.md → Chat, Split view): a fill over each line, a 2px marker beside them, and
// a "Cited passage" label. The canvas exposes no text, so screen readers get the passage from the hidden paragraph.
export function PassageHighlight({ boxes, scale, text }: Props) {
  const top = Math.min(...boxes.map((b) => b.y)) * scale;
  const bottom = Math.max(...boxes.map((b) => b.y + b.height)) * scale;
  const left = Math.min(...boxes.map((b) => b.x)) * scale - MARKER_GAP;
  return (
    <>
      <div aria-hidden="true">
        {boxes.map((b, i) => (
          <span
            key={i}
            data-testid="passage-box"
            className={styles.hlBox}
            style={{ left: `${b.x * scale}px`, top: `${b.y * scale}px`, width: `${b.width * scale}px`, height: `${b.height * scale}px` }}
          />
        ))}
        <span className={styles.hlMarker} style={{ left: `${left}px`, top: `${top}px`, height: `${bottom - top}px` }} />
        <span className={styles.hlLabel} style={{ left: `${left}px`, top: `${top}px` }}>
          Cited passage
        </span>
      </div>
      <p className="visually-hidden">{`Cited passage begins. ${text} Cited passage ends.`}</p>
    </>
  );
}
