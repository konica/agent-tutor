import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import type { Rating } from "../../api/chat";
import { IconButton } from "../../components/Button/IconButton";
import styles from "./AnswerRating.module.css";

const THANKS: Record<Rating, string> = {
  up: "Thanks — glad it helped.",
  down: "Thanks — your feedback helps improve answers.",
};
const FAILED = "Your rating couldn't be saved. Try again.";

// Helpful / Not helpful for one answer (DESIGN.md → Chat). The clicked button shows pressed at once and goes back to the
// saved rating if saving fails. A pressed button doesn't un-press: clicking it saves nothing.
export function AnswerRating({ rating, onRate }: { rating: Rating | null; onRate: (rating: Rating) => Promise<void> }) {
  const [pending, setPending] = useState<Rating | null>(null);
  const [failed, setFailed] = useState(false);
  const shown = pending ?? rating;
  // Only present once there is something to say, so an unrated answer adds no status region to the page.
  const note = failed ? FAILED : shown ? THANKS[shown] : null;

  async function rate(next: Rating) {
    if (next === shown) return;
    setFailed(false);
    setPending(next);
    try {
      await onRate(next);
    } catch {
      setFailed(true);
    } finally {
      setPending(null);
    }
  }

  return (
    <span className={styles.rating}>
      <IconButton label="Helpful" icon={ThumbsUp} aria-pressed={shown === "up"} onClick={() => void rate("up")} />
      <IconButton label="Not helpful" icon={ThumbsDown} aria-pressed={shown === "down"} onClick={() => void rate("down")} />
      {note && (
        <span className={styles.note} role="status">
          {note}
        </span>
      )}
    </span>
  );
}
